import threading
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer

from modules.ui.Chat.main import Chat
from modules.ui.Networks.main import Networks
from modules.ui.Networks.add_discovery_source import AddDiscoverySource
from modules.ui.Networks.create_group import CreateGroup


# Structs for objects
class Group:
	def __init__(self, name) -> None:
		self.name = name


class Node:
	def __init__(self, name) -> None:
		self.name = name


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

	def __init__(self, net, serve, port, node_name, node_ip) -> None:
		super().__init__()
		self.net = net
		self.chat = None
		self.networks = None
		self.serve = serve
		self.port = port
		self.node_name = node_name
		self.node_ip = node_ip

	async def on_mount(self):
		chat = self.query_one("Chat")
		self.chat = chat
		networks = self.query_one("Networks")
		self.networks = networks
		self.net.register_ui(self)
		thread = threading.Thread(
			target=self.serve, args=(self.port, self.net, self.node_name, self.node_ip), daemon=True
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
