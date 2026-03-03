import pytest
import docker
from agent47.sandbox.docker_client import Sandbox
import os

@pytest.fixture
def sandbox():
    # Setup
    sb = Sandbox(image="python:3.10-slim")
    container_id = sb.start()
    
    yield sb
    
    # Teardown
    sb.stop()

def test_sandbox_start_stop(sandbox):
    assert sandbox.container is not None
    assert sandbox.container.status == "created" or "running"

def test_sandbox_execute_command(sandbox):
    output = sandbox.execute_command("echo 'Agent 47 Online'")
    assert "Agent 47 Online" in output

def test_sandbox_read_write_file(sandbox):
    test_file_path = "/workspace/test.txt"
    test_content = "Target acquired."
    
    # Needs a directory to put it in
    sandbox.execute_command("mkdir -p /workspace")
    
    # Write it
    sandbox.write_file_in_container(test_file_path, test_content)
    
    # Read it back
    output = sandbox.read_file_from_container(test_file_path)
    assert test_content in output
