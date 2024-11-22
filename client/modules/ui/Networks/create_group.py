from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import Input, Button, Label


class CreateGroup(ModalScreen):
	"""Screen with a dialog for creating a new group"""

	DEFAULT_CSS = """
	CreateGroup {
    align: center middle;
    background: rgba(0,0,0, 0.75);
	}

	#dialog {
			grid-size: 2;
			grid-gutter: 1 2;
    		grid-rows: 1 1fr 1fr 3;
			padding: 0 1;
			width: 60;
			height: 19;
			border: thick $background 80%;
			background: $surface;
	}

	#group-label {
		column-span: 2;
	}

	Input {
			column-span: 2;
			height: 1fr;
			width: 1fr;
			content-align: center middle;
	}
	"""

	def compose(self) -> ComposeResult:
		yield Grid(
			Label("Create a new group", id="group-label"),
			Input(id="nds_ip_input", placeholder="NDS server IP"),
			Input(id="name_input", placeholder="Group name"),
			Button("Cancel", variant="error"),
			Button("Create", variant="primary", id="create"),
			id="dialog",
		)

	async def on_button_pressed(self, event: Button.Pressed) -> None:
		if event.button.id == "create":
			nds_ip = self.query_one("#nds_ip_input").value
			name = self.query_one("#name_input").value

			# prints to dev console for debugging
			print(nds_ip, name)

		self.app.pop_screen()
