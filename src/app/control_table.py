"""What the controls do in each screen: buttons, confirm, back, initials keys,
and which method draws each state. Every value names an App method."""
from __future__ import annotations

from state import State

#: menu button id -> App method (no arguments)
BUTTON_ACTIONS: dict[str, str] = {
    "play": "_start_game",
    "again": "_start_game",
    "howto": "_enter_howto",
    "settings": "_enter_settings",
    "scores": "_enter_scores",
    "quit": "_quit",
    "resume": "_resume",
    "apply": "_settings_apply",
    "cancel": "_settings_cancel",
    "defaults": "_settings_restore_defaults",
    "confirm_yes": "_accept_confirm",
    "confirm_no": "_decline_confirm",
}

#: buttons that ask first: id -> the question
CONFIRM_PROMPTS: dict[str, str] = {
    "restart": "Restart the current game?",
    "title": "Return to title? Progress is lost.",
    "quit_desktop": "Quit to desktop?",
}

#: a confirmed question -> App method
CONFIRMED_ACTIONS: dict[str, str] = {
    "restart": "_start_game",
    "title": "_goto_title",
    "quit_desktop": "_quit",
}

#: Enter / fire on a screen that is not a menu -> App method
CONFIRM_ACTIONS: dict[State, str] = {
    State.NAME_ENTRY: "_submit_initials",
    State.HIGH_SCORES: "_leave_scores",
    State.READY: "_launch_craft",
    State.LIFE_LOST: "_finish_transition",
    State.LEVEL_COMPLETE: "_finish_transition",
}

#: screens where Enter activates the focused menu button
MENU_STATES = frozenset({State.TITLE, State.GAME_OVER, State.VICTORY,
                         State.SETTINGS, State.HOW_TO_PLAY, State.PAUSED})

#: Esc / back on each screen -> App method
BACK_ACTIONS: dict[State, str] = {
    State.NAME_ENTRY: "_cancel_name_entry",
    State.HIGH_SCORES: "_leave_scores",
    State.TITLE: "_quit",
    State.HOW_TO_PLAY: "_return_from_submenu",
    State.SETTINGS: "_settings_cancel",
    State.PAUSED: "_back_from_pause",
    State.GAME_OVER: "_goto_title",
    State.VICTORY: "_goto_title",
    State.PLAYING: "_pause",
    State.READY: "_pause",
}

#: initials entry: pygame key constant name -> App method
NAME_ENTRY_KEYS: dict[str, str] = {
    "K_LEFT": "_initial_left", "K_a": "_initial_left",
    "K_RIGHT": "_initial_right", "K_d": "_initial_right",
    "K_UP": "_initial_up", "K_w": "_initial_up",
    "K_DOWN": "_initial_down", "K_s": "_initial_down",
    "K_BACKSPACE": "_initial_erase",
}

#: state -> the App method that draws its screen
SCREENS: dict[State, str] = {
    State.TITLE: "_draw_title_screen",
    State.READY: "_draw_flight",
    State.PLAYING: "_draw_flight",
    State.LIFE_LOST: "_draw_flight",
    State.LEVEL_COMPLETE: "_draw_flight",
    State.PAUSED: "_draw_paused",
    State.GAME_OVER: "_draw_result",
    State.VICTORY: "_draw_result",
    State.NAME_ENTRY: "_draw_name_entry",
    State.HIGH_SCORES: "_draw_high_scores",
    State.SETTINGS: "_draw_settings",
    State.HOW_TO_PLAY: "_draw_howto",
}

__all__ = ["BACK_ACTIONS", "BUTTON_ACTIONS", "CONFIRMED_ACTIONS", "CONFIRM_ACTIONS",
           "CONFIRM_PROMPTS", "MENU_STATES", "NAME_ENTRY_KEYS", "SCREENS"]
