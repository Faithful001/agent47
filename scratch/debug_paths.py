import os
from agent47.config.config import WORKSPACE_BASE_DIR

print(f"WORKSPACE_BASE_DIR: {WORKSPACE_BASE_DIR}")
print(f"Is absolute: {os.path.isabs(WORKSPACE_BASE_DIR)}")
print(f"Abspath: {os.path.abspath(WORKSPACE_BASE_DIR)}")

workspace_name = "cortex-ai-server.git"
workspace_dir = os.path.join(WORKSPACE_BASE_DIR, workspace_name)
print(f"workspace_dir: {workspace_dir}")
print(f"Abspath workspace_dir: {os.path.abspath(workspace_dir)}")
