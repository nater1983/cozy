import cozy.artwork_cache as artwork_cache
import cozy.db as db
import cozy.player as player
import cozy.tools as tools
from cozy.sleep_timer import SleepTimer
from cozy.playback_speed import PlaybackSpeed
from cozy.tools import RepeatedTimer

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gtk, Gdk, Gst, GLib

class Titlebar:
    """
    This class contains all titlebar logic.
    """
    # main ui class
    ui = None
    # Titlebar timer for ui updates on position
    play_status_updater = None
    # Is the mouse button currently down on the progress scale?
    progress_scale_clicked = False
    current_book = None
    # Remaining time for this book in seconds
    # This doesn't include the current track
    # and will only be refreshed when the loaded track changes!
    current_remaining = 0

    def __init__(self, ui):
        self.ui = ui

        # init buttons
        self.play_button = self.ui.get_object("play_button")
        self.prev_button = self.ui.get_object("prev_button")
        self.volume_button = self.ui.get_object("volume_button")
        self.timer_button = self.ui.get_object("timer_button")
        self.playback_speed_button = self.ui.get_object("playback_speed_button")
        self.search_button = self.ui.get_object("search_button")
        self.menu_button = self.ui.get_object("menu_button")
        self.remaining_event_box = self.ui.get_object("remaining_event_box")

        # init labels
        self.title_label = self.ui.get_object("title_label")
        self.subtitle_label = self.ui.get_object("subtitle_label")
        self.current_label = self.ui.get_object("current_label")
        self.current_label.set_visible(False)
        self.remaining_label = self.ui.get_object("remaining_label")
        self.remaining_label.set_visible(False)

        # init images
        self.play_img = self.ui.get_object("play_img")
        self.pause_img = self.ui.get_object("pause_img")
        self.cover_img = self.ui.get_object("cover_img")
        self.cover_img_box = self.ui.get_object("cover_img_box")

        # init progress scale
        self.progress_scale = self.ui.get_object("progress_scale")
        self.progress_scale.set_increments(30.0, 60.0)
        self.progress_scale.set_visible(False)

        self.status_stack = self.ui.get_object("status_stack")
        self.status_label = self.ui.get_object("status_label")
        self.update_progress_bar = self.ui.get_object("update_progress_bar")

        self.throbber = self.ui.get_object("spinner")
        self.throbber.set_visible(False)

        self.progress_bar = self.ui.get_object("progress_bar")

        self.__init_signals()

        # elementaryos specific stuff
        if tools.is_elementary():
            self.cover_img_box.props.width_request = 28
            self.cover_img_box.props.height_request = 28

        # app menu
        self.menu_builder = Gtk.Builder.new_from_resource("/de/geigi/cozy/app_menu.ui")
        menu = self.menu_builder.get_object("app_menu")
        self.menu_button.set_menu_model(menu)

    def __init_signals(self):
        self.play_button.connect("clicked", self.__on_play_pause_clicked)
        self.prev_button.connect("clicked", self.__on_rewind_clicked)
        self.volume_button.connect("value-changed", self.__on_volume_changed)
        self.remaining_event_box.connect("button-release-event", self._on_remaining_clicked)

        # init progress scale
        self.progress_scale.connect("value-changed", self.update_ui_time)
        self.progress_scale.connect("button-release-event", self.__on_progress_clicked)
        self.progress_scale.connect("button-press-event", self.__on_progress_press)
        self.progress_scale.connect("key-press-event", self.__on_progress_key_pressed)

        player.add_player_listener(self.__player_changed)

    def activate(self):
        # attach to child event signals
        self.ui.speed.add_listener(self.__on_playback_speed_changed)

        # attach popovers
        self.timer_button.set_popover(self.ui.sleep_timer.get_popover())
        self.playback_speed_button.set_popover(self.ui.speed.get_popover())
        self.search_button.set_popover(self.ui.search.get_popover())

    def block_ui_buttons(self, block, scan=False):
        """
        Block the ui buttons when gui actions are in progress.
        :param block: Boolean
        """
        sensitive = not block
        self.play_button.set_sensitive(sensitive)
        self.volume_button.set_sensitive(sensitive)
        self.prev_button.set_sensitive(sensitive)
        self.timer_button.set_sensitive(sensitive)
        self.playback_speed_button.set_sensitive(sensitive)
        if scan:
            self.search_button.set_sensitive(sensitive)

    def play(self):
        """
        """
        self.play_button.set_image(self.pause_img)
        self.__set_play_status_updater(True)

    def pause(self):
        """
        """
        self.play_button.set_image(self.play_img)
        self.__set_play_status_updater(False)

    def stop(self):
        """
        Remove all information about a playing book from the titlebar.
        """
        self.play_button.set_image(self.play_img)
        self.__set_play_status_updater(False)

        self.title_label.set_text("")
        self.subtitle_label.set_text("")

        self.cover_img.set_from_pixbuf(None)

        self.progress_scale.set_range(0, 0)
        self.progress_scale.set_range(0, 0)
        self.progress_scale.set_visible(False)
        self.progress_scale.set_sensitive(False)

        self.remaining_label.set_visible(False)
        self.current_label.set_visible(False)

        self.block_ui_buttons(True)

    def set_title_cover(self, pixbuf):
        """
        Sets the cover in the title bar.
        """
        self.cover_img.set_from_pixbuf(pixbuf)
        self.cover_img.set_tooltip_text(player.get_current_track().book.name)

    def set_progress_scale_width(self, width):
        self.progress_scale.props.width_request = width

    def update_ui_time(self, widget):
        """
        Displays the value of the progress slider in the text boxes as time.
        """
        val = int(self.progress_scale.get_value())
        m, s = divmod(val, 60)
        self.current_label.set_markup(
            "<tt><b>" + str(m).zfill(2) + ":" + str(s).zfill(2) + "</b></tt>")
        track = player.get_current_track()

        if track is not None:
            remaining_secs = int((track.length / self.ui.speed.get_speed()) - val)

            if tools.get_glib_settings().get_boolean("titlebar-remaining-time"):
                remaining_secs += (self.current_remaining / self.ui.speed.get_speed())
                self.remaining_label.set_markup(
                    "<tt><b>-" + tools.seconds_to_str(remaining_secs) + "</b></tt>")
            else:
                remaining_mins, remaining_secs = divmod(remaining_secs, 60)

                self.remaining_label.set_markup(
                    "<tt><b>-" + str(remaining_mins).zfill(2) + ":" + str(remaining_secs).zfill(2) + "</b></tt>")

        self.ui.update_book_popover_time()

    def update_track_ui(self):
        # set data of new stream in ui
        track = player.get_current_track()
        self.title_label.set_text(track.book.name)
        self.subtitle_label.set_text(track.name)
        self.block_ui_buttons(False)
        self.progress_scale.set_sensitive(True)
        self.progress_scale.set_visible(True)

        # only change cover when book has changed
        if self.current_book is not track.book:
            self.current_book = track.book
            if tools.is_elementary():
                size = 28
            else:
                size = 40
            self.set_title_cover(artwork_cache.get_cover_pixbuf(track.book, size))

        self.current_remaining = db.get_book_remaining(self.current_book, False)
        m,s = player.get_current_duration_ui()
        value = 60 * m + s
        total = player.get_current_track().length / self.ui.speed.get_speed()
        self.progress_scale.set_range(0, total)
        self.progress_scale.set_value(value)
        self.update_ui_time(None)

        self.current_label.set_visible(True)
        self.remaining_label.set_visible(True)

    def switch_to_working(self, message, first):
        """
        Switch the UI state to working.
        This is used for example when an import is currently happening.
        This blocks the user from doing some stuff like starting playback.
        """
        self.throbber.set_visible(True)
        self.throbber.start()
        self.status_label.set_text(message)
        if not first:
            self.update_progress_bar.set_fraction(0)
            self.status_stack.props.visible_child_name = "working"

    def switch_to_playing(self):
        """
        Switch the UI state back to playing.
        This enables all UI functionality for the user.
        """
        self.status_stack.props.visible_child_name = "playback"
        self.throbber.stop()
        self.throbber.set_visible(False)

    def load_last_book(self):
        if db.Settings.get().last_played_book is not None:
            self.update_track_ui()
            self.update_ui_time(self.progress_scale)
            cur_m, cur_s = player.get_current_duration_ui()
            self.progress_scale.set_value(cur_m * 60 + cur_s)

            pos = int(player.get_current_track().position)
            if tools.get_glib_settings().get_boolean("replay"):
                log.info("Replaying the previous 30 seconds.")
                amount = 30 * 1000000000
                if (pos < amount):
                    pos = 0
                else:
                    pos = pos - amount
            self.progress_scale.set_value(int(pos / 1000000000))

    def __on_play_pause_clicked(self, button):
        """
        Play/Pause the player.
        """
        player.play_pause(None)
        pos = self.ui.get_playback_start_position()
        player.jump_to_ns(pos)

    def __on_rewind_clicked(self, button):
        """
        """
        seconds = 30 * self.ui.speed.get_speed()
        player.rewind(seconds)

        # we want to see the jump imediatly therefore we apply the new time manually
        if self.progress_scale.get_value() > 30:
            self.progress_scale.set_value(self.progress_scale.get_value() - 30)
        else:
            self.progress_scale.set_value(0)

    def _on_remaining_clicked(self, widget, sender):
        """
        Switch between displaying the time for a track or the whole book.
        """
        if widget.get_name is not "titlebar_remaining_time_eventbox":
            if tools.get_glib_settings().get_boolean("titlebar-remaining-time"):
                tools.get_glib_settings().set_boolean("titlebar-remaining-time", False)
            else:
                tools.get_glib_settings().set_boolean("titlebar-remaining-time", True)

        self.update_ui_time(None)
        
        return True

    def __on_volume_changed(self, widget, value):
        """
        Sets the ui value in the player.
        """
        player.set_volume(value)

    def __on_progress_press(self, widget, sender):
        """
        Remember that progress scale is clicked so it won't get updates from the player.
        """
        self.progress_scale_clicked = True

        # If the user drags the slider we don't want to jump back
        # another 30 seconds on first play
        if self.ui.first_play:
            self.ui.first_play = False

        return False

    def __on_progress_clicked(self, widget, sender):
        """
        Jump to the slided time and release the progress scale update lock.
        """
        player.jump_to(self.progress_scale.get_value() * self.ui.speed.get_speed())
        self.progress_scale_clicked = False

        return False

    def __on_progress_key_pressed(self, widget, event):
        """
        Jump to the modified time.
        """
        old_val = self.progress_scale.get_value()
        if event.keyval == Gdk.KEY_Up or event.keyval == Gdk.KEY_Left:
            if old_val > 30.0:
                player.jump_to(old_val - 30)
            else:
                player.jump_to(0)
        elif event.keyval == Gdk.KEY_Down or event.keyval == Gdk.KEY_Right:
            upper = self.progress_scale.get_adjustment().get_upper()
            if old_val + 30.0 < upper:
                player.jump_to(old_val + 30)
            else:
                player.jump_to(upper)

        return False

    def __set_play_status_updater(self, enable):
        """
        Starts/stops the play status ui update timer.
        Restarts if enable is True and the timer is already running.
        :params enable: Boolean
        """
        if self.play_status_updater is not None:
            self.play_status_updater.stop()
            self.play_status_updater = None

        if enable and self.ui.is_playing:
            self.play_status_updater = RepeatedTimer(
                1.0, self.__update_time)
            self.play_status_updater.start()

    def __update_time(self):
        """
        Update the current and remaining time.
        """
        if not self.progress_scale_clicked:
            cur_m, cur_s = player.get_current_duration_ui()
            Gdk.threads_add_idle(GLib.PRIORITY_DEFAULT_IDLE,
                                 self.progress_scale.set_value, (cur_m * 60 + cur_s))

    def __on_playback_speed_changed(self, event, message):
        """
        Handler for events that occur the playback speed object.
        """
        if event == "playback-speed-changed":
            speed = message
            m,s = player.get_current_duration_ui()
            value = 60 * m + s
            total = player.get_current_track().length / speed
            self.progress_scale.set_range(0, total)
            self.progress_scale.set_value(value)
            self.update_ui_time(None)

    def __player_changed(self, event, message):
        """
        Listen to and handle all gst player messages that are important for the ui.
        """
        if event == "track-changed":
            self.update_track_ui()

    def close(self):
        if self.play_status_updater is not None:
            self.play_status_updater.stop()