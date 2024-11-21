from multiprocessing import Process
from service.server import serve, create_group, join_network, send_message, message_broadcast, store_message, get_group_info, get_messages, leave_network, liveness
import pytest
import shelve
import os
from unittest.mock import MagicMock, patch


def start_server():
    serve(port=5000)

@pytest.fixture
def mock_environment(tmp_path):
    groups_path = tmp_path / "test_groups.db"
    messages_path = tmp_path / "test_messages.db"
    nds_server_mock = {}
    
    with shelve.open(str(groups_path), writeback=True) as groups, \
         shelve.open(str(messages_path), writeback=True) as message_store, \
         patch("service.server.groups", groups), \
         patch("service.server.message_store", message_store), \
         patch("service.server.nds_server", {
             "127.0.0.1": MagicMock(get_proxy=MagicMock(
                 return_value=MagicMock(
                    create_group=MagicMock(
                        return_value=MagicMock(
                            success=True, 
                            group_id="group_1"
                            )
                        )
                    )
             ))
         }) as nds_server_mock, \
         patch("service.server.send_message_to_peer", MagicMock()) as send_message_to_peer:
        yield {
            "groups": groups,
            "message_store": message_store,
            "nds_server": nds_server_mock,
            "send_message_to_peer": send_message_to_peer
        }


def test_create_group_success(mock_environment):
    groups = mock_environment['groups']
    create_group("Test Group", "127.0.0.1")
    assert len(groups) > 0
    group_id = list(groups.keys())[0]
    assert groups[group_id]["group_name"] == "Test Group"
    assert groups[group_id]["self_id"] == 0
    assert groups[group_id]["leader_id"] == 0


def test_create_group_already_exists(mock_environment):
    groups = mock_environment['groups']
    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": 0,
        "leader_id": 0,
        "peers": {
            0: {"name": "bob", "ip": "127.0.0.1"}
        },
    }

    mock_environment["nds_server"]["127.0.0.1"].get_proxy.return_value.create_group.return_value = MagicMock(
        success=True, group_id="group_1"
    )

    create_group("Test Group", "127.0.0.1")
    assert groups["group_1"]["group_name"] == "Test Group"  # Ensures data is intact


def test_create_group_leader_assignment(mock_environment):
    mock_environment["nds_server"]["127.0.0.1"].get_proxy.return_value.create_group.return_value = MagicMock(
        success=True, group_id="group_1"
    )

    create_group("Test Group", "127.0.0.1")

    groups = mock_environment['groups']
    assert groups["group_1"]["leader_id"] == 0
    assert groups["group_1"]["self_id"] == 0


def test_create_group_empty_name(mock_environment):
    with pytest.raises(ValueError, match="Group name cannot be empty"):
        create_group("", "127.0.0.1")


def test_create_multiple_groups(mock_environment):
    mock_environment["nds_server"]["127.0.0.1"].get_proxy.return_value.create_group.side_effect = [
        MagicMock(success=True, group_id="group_1"),
        MagicMock(success=True, group_id="group_2"),
    ]

    create_group("Test Group 1", "127.0.0.1")
    create_group("Test Group 2", "127.0.0.1")

    groups = mock_environment['groups']
    assert "group_1" in groups
    assert "group_2" in groups
    assert groups["group_1"]["group_name"] == "Test Group 1"
    assert groups["group_2"]["group_name"] == "Test Group 2"



def test_join_group_success(mock_environment):
    groups = mock_environment['groups']
    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": 0,
        "leader_id": 0,
        "peers": {}
    }

    response = join_network("group_1", "127.0.0.2", "peer_2")
    assert response.success
    assert "peer_2" in [peer["name"] for peer in groups["group_1"]["peers"].values()]


def test_join_group_leader(mock_environment):
    groups = mock_environment['groups']
    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": 0,
        "leader_id": 0,
        "peers": {}
    }

    response=join_network("group_1", "127.0.0.2", "peer_2")
    assert response.success == True
    assert response.message == "Joined a group successfully"
    assert response.data["peers"]


def test_join_group_no_leader(mock_environment):
    groups = mock_environment['groups']
    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": 2,
        "leader_id": 0,
        "peers": {}
    }

    response=join_network("group_1", "127.0.0.2", "peer_2")
    assert response.success == False
    assert response.message == "Only leader can validate users."


def test_join_network_duplicate_name(mock_environment):
    groups = mock_environment['groups']
    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": 0,
        "leader_id": 0,
        "peers": {
            1: {"name": "peer_1", "ip": "127.0.0.1"},
        }
    }

    response = join_network("group_1", "127.0.0.2", "peer_1")
    assert not response.success
    assert response.message == "Peer name already exists in the group."


def test_join_network_duplicate_ip(mock_environment):
    groups = mock_environment['groups']
    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": 0,
        "leader_id": 0,
        "peers": {
            1: {"name": "peer_1", "ip": "127.0.0.1"},
        }
    }

    response = join_network("group_1", "127.0.0.1", "peer_2")
    assert not response.success
    assert response.message == "Peer IP already exists in the group."


def test_leave_group_success(mock_environment):
    groups = mock_environment['groups']
    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": 0,
        "leader_id": 0,
        "peers": {
            1: {"name": "peer_1", "ip": "127.0.0.1"},
        }
    }

    response = leave_network("group_1", 1)
    assert response.success
    assert 1 not in groups["group_1"]["peers"]


def test_leave_group_invalid_peer(mock_environment):
    groups = mock_environment['groups']
    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": 0,
        "leader_id": 0,
        "peers": {}
    }

    response = leave_network("group_1", 99)
    assert not response.success
    assert response.message == "Peer not found"


def test_join_group_invalid_group(mock_environment):
    groups = mock_environment['groups']
    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": 0,
        "leader_id": 0,
        "peers": {}
    }
    with pytest.raises(ValueError, match="Group with ID .* does not exist"):
        join_network("invalid_group", "127.0.0.2", "peer_2")


def test_create_group_invalid_nds(mock_environment):
    with pytest.raises(ValueError, match="NDS server with ID .* does not exist"):
        create_group("Invalid Group", "invalid_nds_id")


def test_message_broadcast(mock_environment):
    env = mock_environment
    groups = env["groups"]
    send_message_to_peer = env["send_message_to_peer"]

    peers = {
        "peer_1": {"ip": "127.0.0.1"},
        "peer_2": {"ip": "127.0.0.2"},
        "peer_3": {"ip": "127.0.0.3"}
    }

    groups["group_1"] = {
            "group_name": "Test Group",
            "self_id": "peer_1",
            "leader_id": "leader_1",
            "peers": peers
        }
    
    assert "group_1" in groups 
    assert groups["group_1"]["peers"] == peers
    message_broadcast("Test Message", "msg_1", "group_1", "peer_1")

    assert send_message_to_peer.call_count == 2


def test_self_message_broadcast(mock_environment):
    env = mock_environment
    groups = env["groups"]
    send_message_to_peer = env["send_message_to_peer"]

    peers = {
        "peer_1": {"ip": "127.0.0.1"}
    }

    groups["group_1"] = {
            "group_name": "Test Group",
            "self_id": "peer_1",
            "leader_id": "leader_1",
            "peers": peers
        }
    
    assert "group_1" in groups 
    assert groups["group_1"]["peers"] == peers
    message_broadcast("Test Message", "msg_1", "group_1", "peer_1")

    assert send_message_to_peer.call_count == 0


def test_direct_message_success(mock_environment):
    env = mock_environment
    groups = env['groups']
    send_message_to_peer = env['send_message_to_peer']

    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": 0,
        "leader_id": 0,
        "peers": {
            1: {"name": "peer_1", "ip": "127.0.0.1"},
        }
    }

    response = send_message("Hello", "group_1", 0, 1)
    assert response.success
    assert send_message_to_peer.call_count == 1


def test_create_and_join_group(mock_environment):
    env = mock_environment
    groups = env["groups"]

    create_group("Test Group", "127.0.0.1")
    assert "group_1" in groups
    assert groups["group_1"]["group_name"] == "Test Group"


def test_store_message(mock_environment):
    env = mock_environment
    message_store = env["message_store"]

    store_message("Hello", "msg_1", "group_1", "peer_1")
    messages = message_store.get("group_1", [])
    assert len(messages) == 1
    assert messages[0]["msg"] == "Hello"
    assert messages[0]["msg_id"] == "msg_1"
    assert messages[0]["source_id"] == "peer_1"


def test_store_message_success(mock_environment):
    message_store = mock_environment['message_store']
    store_message("Hello", "msg_1", "group_1", "peer_1")

    messages = message_store["group_1"]
    assert len(messages) == 1
    assert messages[0]["msg"] == "Hello"


def test_get_messages_success(mock_environment):
    message_store = mock_environment['message_store']
    message_store["group_1"] = [
        {"msg": "Hello", "msg_id": "msg_1", "source_id": "peer_1"}
    ]

    messages = get_messages("group_1")
    assert len(messages) == 1
    assert messages[0]["msg"] == "Hello"


def test_get_messages(mock_environment):
    env = mock_environment
    message_store = env["message_store"]

    message_store["group_1"] = [{"msg": "Hello", "msg_id": "msg_1", "source_id": "peer_1"}]
    messages = get_messages("group_1")
    assert messages == [{"msg": "Hello", "msg_id": "msg_1", "source_id": "peer_1"}]


def test_get_group_info(mock_environment):
    env = mock_environment
    groups = env["groups"]

    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": "peer_1",
        "leader_id": "leader_1",
        "peers": {}
    }

    group_name, self_id, leader_id, peers = get_group_info("group_1")

    assert group_name == "Test Group"
    assert self_id == "peer_1"
    assert leader_id == "leader_1"
    assert peers == {}


def test_full_workflow(mock_environment):
    env = mock_environment
    groups = env["groups"]

    server_process = Process(target=start_server)
    server_process.start()

    try:
        create_group("end-to-end test", "127.0.0.1")
        assert "group_1" in groups
        assert groups["group_1"]["group_name"] == "end-to-end test"
    finally:
        server_process.terminate()
        server_process.join()


def test_liveness_success():
    assert liveness("127.0.0.1", 5000)


def test_liveness_failure():
    assert not liveness("192.0.2.1", 5000)


def test_same_peer_name_joins(mock_environment):
    from concurrent.futures import ThreadPoolExecutor

    def join():
        join_network("group_1", "127.0.0.3", "peer_3")

    groups = mock_environment['groups']
    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": 0,
        "leader_id": 0,
        "peers": {}
    }

    with ThreadPoolExecutor(max_workers=10) as executor:
        for _ in range(10):
            executor.submit(join)

    print(groups["group_1"]["peers"])
    assert len(groups["group_1"]["peers"]) == 1


def test_same_peer_ip_joins(mock_environment):
    from concurrent.futures import ThreadPoolExecutor

    def join():
        join_network("group_1", "127.0.0.3", "peer_3")

    groups = mock_environment['groups']
    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": 0,
        "leader_id": 0,
        "peers": {}
    }

    with ThreadPoolExecutor(max_workers=10) as executor:
        for _ in range(10):
            executor.submit(join)

    print(groups["group_1"]["peers"])
    assert len(groups["group_1"]["peers"]) == 1


def test_diff_ip_joins(mock_environment):
    from concurrent.futures import ThreadPoolExecutor

    def join():
        join_network("group_1", "127.0.0.3", "peer_3")
        join_network("group_1", "127.0.0.1", "peer_1")
        join_network("group_1", "127.0.0.2", "peer_2")
        join_network("group_1", "127.0.0.5", "peer_5")

    groups = mock_environment['groups']
    groups["group_1"] = {
        "group_name": "Test Group",
        "self_id": 0,
        "leader_id": 0,
        "peers": {}
    }

    with ThreadPoolExecutor(max_workers=10) as executor:
        for _ in range(10):
            executor.submit(join)

    print(groups["group_1"]["peers"])
    assert len(groups["group_1"]["peers"]) == 4