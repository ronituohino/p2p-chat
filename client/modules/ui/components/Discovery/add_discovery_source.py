from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import Screen
from textual.widgets import Input, Button


class AddDiscoverySource(Screen):
	"""Screen with a dialog to add a new Discovery source"""

	DEFAULT_CSS = """
	AddDiscoverySource {
    align: center middle;
    background: rgba(0,0,0, 0.75);
	}

	#dialog {
			grid-size: 2;
			grid-gutter: 1 2;
			grid-rows: 1fr 3;
			padding: 0 1;
			width: 60;
			height: 11;
			border: thick $background 80%;
			background: $surface;
	}

	#input {
			column-span: 2;
			height: 1fr;
			width: 1fr;
			content-align: center middle;
	}

	Button {
			width: 100%;
	}
	"""

	def compose(self) -> ComposeResult:
		yield Grid(
			Input(id="input"),
			Button("Cancel", variant="error", id="cancel"),
			Button("Add", variant="primary", id="add"),
			id="dialog",
		)

	def on_button_pressed(self) -> None:
		self.app.pop_screen()