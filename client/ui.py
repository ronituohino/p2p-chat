from textual.app import App, ComposeResult, RenderResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Static, Input, Tree
from textual.widget import Widget

from textual.reactive import reactive


class Discovery(Static):
	BORDER_TITLE = "Discovery"

	def compose(self) -> ComposeResult:
		with VerticalScroll():
			yield Static("Horizontally")
			yield Static("Horizontally")
			yield Static("Positioned")
			yield Static("Children")
			yield Static("Horizontally")
			yield Static("Positioned")
			yield Static("Children")
			yield Static("Horizontally")
			yield Static("Positioned")
			yield Static("Children")
			yield Static("Horizontally")
			yield Static("Positioned")
			yield Static("Children")


class Groups(Static):
	BORDER_TITLE = "Groups"

	def compose(self) -> ComposeResult:
		with VerticalScroll():
			tree: Tree[str] = Tree("Dune")
			tree.root.expand()
			characters = tree.root.add("Characters")
			characters.add_leaf("Paul")
			characters.add_leaf("Jessica")
			characters.add_leaf("Chani")
			yield tree


class Message(Widget):
	message = reactive("")
	sender = reactive("")

	def render(self) -> RenderResult:
		return f"@{self.sender}: {self.message}"


class Chat(Widget):
	BORDER_TITLE = "Chat"

	# recompose=True rerenders entire component when chat_log changes
	chat_log = reactive([], recompose=True)

	def on_input_submitted(self, event: Input.Submitted):
		print("hii!!")
		new_chat_log = self.chat_log
		new_chat_log.append(event.value)

	def compose(self) -> ComposeResult:
		with VerticalScroll():
			for c in self.chat_log:
				yield Message(message=c, sender="Roni")
			yield Input(classes="message-input")


class ChatApp(App):
	"""The main ui class"""

	CSS_PATH = "chatapp.tcss"
	BINDINGS = [("a", "add_discovery", "Add Discovery source")]

	def compose(self) -> ComposeResult:
		with Horizontal(classes="column"):
			with Vertical(id="left", classes="column"):
				yield Discovery()
				yield Groups()
			yield Chat()
		yield Footer()

	def action_add_discovery(self) -> None:
		"""An action to add a new Discovery source"""
		print("Implement")


def run():
	app = ChatApp()
	app.run()


if __name__ == "__main__":
	run()
