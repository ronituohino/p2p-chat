from textual.app import ComposeResult
from textual.widgets import Input, Static, RichLog

banner = """
  ██████╗ ██████╗ ██████╗        ██████╗██╗  ██╗ █████╗ ████████╗
  ██╔══██╗╚════██╗██╔══██╗      ██╔════╝██║  ██║██╔══██╗╚══██╔══╝
  ██████╔╝ █████╔╝██████╔╝█████╗██║     ███████║███████║   ██║   
  ██╔═══╝ ██╔═══╝ ██╔═══╝ ╚════╝██║     ██╔══██║██╔══██║   ██║   
  ██║     ███████╗██║           ╚██████╗██║  ██║██║  ██║   ██║   
  ╚═╝     ╚══════╝╚═╝            ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   
"""


class Chat(Static):
	BORDER_TITLE = "Chat"

	DEFAULT_CSS = """
	Chat {
    border: $border;
    background: blue;
    max-width: 70%;
	}

	RichLog {
		overflow-x: hidden; 
	}

	.message-input {
			dock: bottom;
			background: red;
	}
	"""

	def write(self, msg: str):
		self.query_one(RichLog).write(msg, width=66)

	def on_mount(self):
		self.write(banner)

	def on_input_submitted(self, event: Input.Submitted):
		event.input.clear()
		self.write(f"@me: {event.value}")

	def compose(self) -> ComposeResult:
		yield RichLog(wrap=True, auto_scroll=True)
		yield Input(classes="message-input")
