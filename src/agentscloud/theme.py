"""Identidade do hub: cores, dimensões e estilos centralizados."""

from textual.theme import Theme

MIN_WIDTH = 80
MIN_HEIGHT = 24
COMPACT_WIDTH = 100
COMPACT_HEIGHT = 30

PALETTE = {
    "night": "#091321",
    "panel": "#101f32",
    "raised": "#162b42",
    "line": "#29455f",
    "cyan": "#67e8f9",
    "text": "#e6f1fb",
    "muted": "#a2b7cc",
    "success": "#86efac",
    "warning": "#fcd38b",
    "error": "#fda4af",
}

HUB_THEME = Theme(
    name="agentscloud-night", primary=PALETTE["cyan"], secondary=PALETTE["muted"],
    accent=PALETTE["cyan"], background=PALETTE["night"], foreground=PALETTE["text"],
    surface=PALETTE["panel"], panel=PALETTE["raised"], success=PALETTE["success"],
    warning=PALETTE["warning"], error=PALETTE["error"], dark=True,
    variables={"footer-key-foreground": PALETTE["cyan"], "button-focus-text-style": "bold"},
)

CSS = """
Screen { background: $night; color: $text; }
* { scrollbar-color: $line; scrollbar-color-hover: $cyan; scrollbar-color-active: $cyan; scrollbar-background: $panel; }
#shell { height: 1fr; }
#sidebar { width: 25; background: $panel; padding: 1 2; border-right: solid $line; }
#brand { color: $cyan; text-style: bold; height: 2; }
#brand-caption { color: $muted; height: 3; }
#nav-label { color: $muted; height: 2; }
.nav-button { width: 100%; height: 3; margin-bottom: 1; border: none; background: $panel; content-align: left middle; }
.nav-button.selected { background: $raised; color: $cyan; text-style: bold; border-left: thick $cyan; }
.nav-button:focus { border: tall $cyan; }
#sidebar-spacer { height: 1fr; }
#catalog-summary { height: auto; color: $muted; margin-bottom: 1; }
#repo-label { height: 1; color: $cyan; }
#repo-name { height: 1; }
#repo-path { height: 1; color: $muted; }
#workspace { width: 1fr; padding: 1 2; }
#eyebrow { color: $cyan; height: 2; }
#page-title { text-style: bold; height: 2; }
#page-description { color: $muted; height: 3; }
#steps { color: $cyan; height: 2; }
#action-row { height: 3; margin-bottom: 1; }
#start { min-width: 24; }
#activity { width: 6; height: 3; color: $cyan; }
#status { width: 1fr; content-align: right middle; color: $muted; }
#session-log { height: 1fr; min-height: 4; background: $panel; border: round $line; border-title-color: $muted; padding: 0 1; }
#session-log:focus { border: round $cyan; }
#context-hint { height: 2; color: $muted; padding-top: 1; }
Footer { background: $panel; color: $text; }
Button { background: $raised; color: $text; border: tall $line; }
Button:hover { background: $line; }
Button:focus { border: tall $cyan; text-style: bold; }
Button.-primary { background: $cyan; color: $night; border: tall $cyan; }
Button.-primary:hover { background: $text; }
Button.-primary:focus { border: tall $text; }
Button:disabled { opacity: 50%; }
#too-small { display: none; height: 1fr; content-align: center middle; padding: 1 2; }
Screen.too-small #shell { display: none; }
Screen.too-small #too-small { display: block; }
Screen.compact #sidebar { width: 20; padding: 1; }
Screen.compact #workspace { padding: 1; }
Screen.compact #brand-caption { display: none; }
Screen.compact #nav-label { height: 1; }
Screen.compact .nav-button { margin-bottom: 0; }
Screen.compact #page-description { height: 2; }
Screen.compact #eyebrow { height: 1; }
Screen.compact #context-hint { height: 1; padding: 0; }
.dialog-screen { align: center middle; background: $night 80%; }
#dialog { width: 85%; max-width: 104; height: 85%; padding: 1 2; border: round $cyan; background: $panel; }
#dialog-title { height: auto; max-height: 4; color: $cyan; text-style: bold; margin-bottom: 1; }
#dialog-hint { height: auto; max-height: 3; color: $muted; margin-bottom: 1; }
#prompt-scroll { height: 1fr; }
#prompt-message { height: auto; margin-bottom: 1; }
#answer { margin-bottom: 1; }
#choices, #review-content { height: 1fr; background: $night; border: solid $line; }
#review-content:focus { border: solid $cyan; }
#dialog-actions { height: 3; margin-top: 1; align-horizontal: right; }
#dialog-actions Button { margin-left: 1; min-width: 16; }
#category { height: 3; margin-bottom: 1; }
#agent-list { height: 1fr; min-height: 3; border: solid $line; background: $night; }
#agent-list:focus { border: solid $cyan; }
#agent-details { height: 4; color: $muted; padding-top: 1; }
#selection-summary { height: 1; color: $cyan; }
#selection-tools { height: 3; }
#selection-tools Button { min-width: 16; margin-right: 1; }
#dialog-size { display: none; height: 1fr; content-align: center middle; padding: 1 2; }
Screen.compact #dialog { width: 100%; height: 100%; padding: 0 1; }
Screen.compact #dialog-title { margin-bottom: 0; max-height: 3; }
Screen.compact #dialog-hint { margin-bottom: 0; max-height: 2; }
Screen.compact #agent-details { height: 2; padding-top: 0; }
Screen.compact #dialog-actions { margin-top: 0; }
Screen.too-small #dialog { display: none; }
Screen.too-small #dialog-size { display: block; }
Input, Select, OptionList { background: $night; color: $text; }
Input:focus, Select:focus { border: tall $cyan; }
OptionList > .option-list--option-highlighted { background: $raised; color: $cyan; }
SelectionList > .selection-list--button-selected { color: $cyan; }
"""

for _name, _color in PALETTE.items():
    CSS = CSS.replace("$" + _name, _color)
