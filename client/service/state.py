import threading
from structs.client import Group, Message
from tinyrpc import RPCClient
from tinyrpc.protocols.jsonrpc import JSONRPCProtocol
from tinyrpc.transports.http import HttpPostClientTransport


class AppState:
	_instance = None

	def __new__(cls):
		if not cls._instance:
			cls._instance = super(AppState, cls).__new__(cls)
			cls._initialize_state(cls._instance)
		return cls._instance

	@staticmethod
	def _initialize_state(instance):
		"""Initializes all shared state variables."""
		instance.name = None
		instance.active_group: Group = None  # type: ignore
		instance.logical_clock = 0

		instance.message_store: dict[str, Message] = {}  # type: ignore
		instance.received_messages = set()
		instance.message_timestamps = {}
		instance.MESSAGE_TTL = 300

		instance.last_node_response: dict[str, int] = {}  # type: ignore # key is node_id, used to check when last heard from node, value is the overseer cycles

		instance.node_port = 5001
		instance.nds_port = 5002

		instance.nds_servers: dict[str, RPCClient] = {}  # type: ignore
		instance.dispatcher = None
		instance.networking = None

		instance.message_store_lock = threading.Lock()
		instance.received_messages_lock = threading.Lock()

		instance.env = None

		instance.leader_election = None
		instance.create_group = None
		instance.request_to_join_group = None

		instance.heartbeat_min_interval = 2
		instance.heartbeat_max_interval = 4

		instance.heartbeat: threading.Thread = None
		instance.heartbeat_counter = 0  # set to the id of the heartbeat
		instance.heartbeat_kill_flags = set()


	@property
	def active_group(self):
		return self._active_group

	@active_group.setter
	def active_group(self, group):
		self._active_group = group

	def increment_clock(self):
		self.logical_clock += 1

	def reset_state(self):
		"""Resets state variables to their initial values."""
		self._initialize_state(self)

	def create_rpc_client(self, ip, port):
		"""
		Create a remote client object.
		This itself does not attempt to send anything, so it cannot fail.
		"""
		rpc_client = RPCClient(
			JSONRPCProtocol(),
			HttpPostClientTransport(f"http://{ip}:{port}/", timeout=5),
		)
		return rpc_client

	def get_ip(self):
		return self.env.get("REMOTE_ADDR", "Unknown IP")
