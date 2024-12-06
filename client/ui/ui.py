import threading
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer

from .Chat.main import Chat
from .Networks.main import Networks
from .Networks.add_discovery_source import AddDiscoverySource
from .Networks.create_group import CreateGroup


class ChatApp(App):
	"""The main ui class"""

	DEFAULT_CSS = """
	Networks {
	width: 30%;
	}

	$border: round darkblue;
	"""

	BINDINGS = [
		("a", "add_discovery", "Add Discovery source"),
		("c", "create_group", "Create Group"),
	]

	def __init__(self, net, serve, node_name) -> None:
		super().__init__()
		self.net = net
		self.chat = None
		self.networks = None
		self.serve = serve
		self.node_name = node_name

	async def on_mount(self):
		chat = self.query_one("Chat")
		self.chat = chat
		networks = self.query_one("Networks")
		self.networks = networks

		self.net.register_ui(self)

		if self.serve is not None:
			thread = threading.Thread(
				target=self.serve, args=(self.net, self.node_name), daemon=True
			)
			thread.start()

	def compose(self) -> ComposeResult:
		with Horizontal():
			yield Networks()
			yield Chat()
		yield Footer()

	def action_add_discovery(self) -> None:
		"""An action to add a new Discovery source"""
		self.push_screen(AddDiscoverySource())

	def action_create_group(self) -> None:
		"""An action to create a new group"""
		self.push_screen(CreateGroup())

	def check_action(self, action, parameters):
		if self.networks is None:
			return None
		elif action == "create_group" and not self.networks.network_labels:
			return None
		return True
