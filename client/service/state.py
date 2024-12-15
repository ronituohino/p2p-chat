import threading
from structs.client import Group
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
		instance._active_group: Group = None
		instance.logical_clock = 0

		instance.message_store = {}
		instance.received_messages = set()
		instance.message_timestamps = {}
		instance.MESSAGE_TTL = 300

		instance.last_node_response = {}  # key is node_id, used to check when last heard from node, value is the overseer cycles

		instance.node_port = 5001
		instance.nds_port = 5002

		instance.nds_servers = {}
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

		instance.heartbeat = None
		instance.heartbeat_counter = 0  # set to the id of the heartbeat
		instance.heartbeat_kill_flags = set()

		instance.crawler = None
		instance.crawler_refresh_rate = 5

		instance.overseer = None
		instance.overseer_counter = 0  # set to the id of the heartbeat
		instance.overseer_kill_flags = set()
		instance.overseer_lock = threading.Lock()
		instance.overseer_cycles_timeout = 6
		instance.overseer_interval = 1

	@property
	def active_group(self):
		return self._active_group

	@active_group.setter
	def active_group(self, group):
		self._active_group = group
		if group:
			with self.overseer_lock:
				self.last_node_response = {node_id: 0 for node_id in group.peers.keys()}

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
		return rpc_client.get_proxy()

	def get_ip(self):
		if not self.env:
			return "Unknown IP"
		return self.env.get("REMOTE_ADDR", "Unknown IP")
