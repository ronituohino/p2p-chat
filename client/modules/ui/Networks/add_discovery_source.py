from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Input, Button, Label


class AddDiscoverySource(ModalScreen):
	"""Screen with a dialog to add a new Discovery source"""

	DEFAULT_CSS = """

	AddDiscoverySource {
		align: center middle;
		background: $background 75%;
	}

	#dialog {
		padding: 0 2;
		width: 60;
		height: 13;
		border: thick $background 90%;
		background: $surface;
	}

	#name_input, #nds_ip {
		margin-top: 1;
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
		margin-top: 1;
		height: 1;
	}
	"""

	def compose(self) -> ComposeResult:
		with Vertical(id="dialog"):
			yield Label("Add Discovery Source", id="nds-label")
			yield Input(id="name_input")
			yield Input(id="nds_ip")
			with Horizontal(id="buttons"):
				yield Button.error("Cancel")
				yield Button("Add", variant="primary", id="add")

	def on_mount(self) -> None:
		name_input = self.query_one("#name_input")
		name_input.border_title = "Name"
		ip_input = self.query_one("#nds_ip")
		ip_input.border_title = "NDS IP Address"

	async def on_button_pressed(self, event: Button.Pressed) -> None:
		if event.button.id == "add":
			nds_ip = self.query_one("Input").value
			groups = await self.app.net.add_discovery_source(nds_ip)
			self.app.networks.add_groups(nds_ip, groups)
			self.app.networks.refresh_networks()
		self.app.pop_screen()
