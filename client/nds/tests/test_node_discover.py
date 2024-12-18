import pytest
import socket
from multiprocessing import Process
from tinyrpc import RPCClient
from tinyrpc.protocols.jsonrpc import JSONRPCProtocol
from tinyrpc.transports.http import HttpPostClientTransport
from main import serve
import time

@pytest.fixture(scope="module", autouse=True)
def server_process():
	process = Process(target=serve, args=(5002,))
	process.start()

	for _ in range(10): 
		try:
			with socket.create_connection(("127.0.0.1", 5002), timeout=1):
				break
		except (socket.timeout, ConnectionRefusedError):
			time.sleep(0.5)
	else:
		process.terminate()
		pytest.fail("Server did not start within the timeout period")

	yield
	process.terminate()
	process.join()


@pytest.fixture
def rpc_client():
	transport = HttpPostClientTransport(f"http://127.0.0.1:5002/")
	client = RPCClient(JSONRPCProtocol(), transport)
	return client


def test_create_group(rpc_client):
	proxy = rpc_client.get_proxy()
	proxy.reset_database() 
	response = proxy.create_group("127.0.0.1", "Test Group")
	assert response["success"]
	assert "group_id" in response["data"]


def test_get_groups(rpc_client):
	proxy = rpc_client.get_proxy()
	proxy.reset_database()
	proxy.create_group("127.0.0.1", "Group 1")
	proxy.create_group("127.0.0.2", "Group 2")
	response = proxy.get_groups()
	assert response["success"]
	assert len(response["data"]["groups"]) == 2


def test_update_group_leader(rpc_client): 
	"""Test updating the group leader."""
	proxy = rpc_client.get_proxy()
	response = proxy.create_group("127.0.0.1", "Group 1")
	assert response["success"]
	group_id = response["data"]["group_id"]
	response = proxy.update_group_leader(group_id, "127.0.0.2")
	assert response["success"]
	assert response["message"] == "Leader update successful"

def test_get_group_leader(rpc_client): 
	"""Test updating the group leader."""
	proxy = rpc_client.get_proxy()
	response = proxy.create_group("127.0.0.1", "Group 1")
	assert response["success"]
	group_id = response["data"]["group_id"]
	response = proxy.get_group_leader(group_id)
	assert response["data"]["leader_ip"] == "127.0.0.1"


