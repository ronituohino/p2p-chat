from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Input, Button, Label, OptionList


class CreateGroup(ModalScreen):
	"""Screen with a dialog for creating a new group"""

	DEFAULT_CSS = """

	CreateGroup {
		align: center middle;
		background: $background 75%;
	}

	#dialog {
		padding: 0 2;
		width: 60;
		height: 16;
		border: thick $background 90%;
		background: $surface;
	}

	#nds_selector {
		margin-top: 1;
		border: solid $accent 80%;
		height: 6;
	}

	#name_input {
		height: 3;
		content-align: left middle;
		border: solid $accent 80%;
	}

	#buttons {
		align: right middle;
	}

	#buttons Button {
		border-top: none;
		border-bottom: none;
		margin-left: 2;
		height: 1;
	}
	"""

	def compose(self) -> ComposeResult:
		with Vertical(id="dialog"):
			yield Label("Create a New Group", id="group-label")
			yield OptionList(*self.app.networks.get_networks(), id="nds_selector")
			yield Input(id="name_input")
			with Horizontal(id="buttons"):
				yield Button.error("Cancel")
				yield Button("Create", variant="primary", id="create")

	def on_mount(self) -> None:
		nds_selection = self.query_one("#nds_selector")
		nds_selection.border_title = "Node Discovery Server"
		name_input = self.query_one("#name_input")
		name_input.border_title = "Group Name"

	async def on_button_pressed(self, event: Button.Pressed) -> None:
		if event.button.id == "create":
			opts = self.query_one("#nds_selector")
			chosen_index = opts.highlighted
			nds_ip = opts.get_option_at_index(chosen_index).prompt
			name = self.query_one("#name_input").value

			created_group = await self.app.net.create_group(name, nds_ip)
			self.app.networks.create_group(nds_ip, created_group)

		self.app.pop_screen()
