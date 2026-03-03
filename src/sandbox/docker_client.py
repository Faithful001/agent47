import docker
import os
import tarfile
import io
import time

class Sandbox:
    def __init__(self, image="python:3.10-slim"):
        self.client = docker.from_env()
        self.image = image
        self.container = None

    def start(self):
        """Starts a fresh docker container."""
        print(f"Starting sandbox with image {self.image}...")
        self.container = self.client.containers.run(
            self.image,
            detach=True,
            tty=True,
            command="tail -f /dev/null" # Keep container alive
        )
        
        # Install basics in the container
        self.execute_command("pip install pytest")
        return self.container.id

    def stop(self):
        """Stops and removes the container."""
        if self.container:
            print("Stopping sandbox...")
            self.container.stop()
            self.container.remove()
            self.container = None

    def execute_command(self, command: str) -> str:
        """Executes a command inside the container and returns the output."""
        if not self.container:
            raise RuntimeError("Sandbox is not running.")
        
        exit_code, output = self.container.exec_run(command)
        return output.decode('utf-8')

    def copy_file_to_container(self, src_path: str, dest_path: str):
        """Copies a local file into the container."""
        if not self.container:
            raise RuntimeError("Sandbox is not running.")
            
        with open(src_path, 'rb') as f:
            file_data = f.read()
            
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode='w') as tar:
            tarinfo = tarfile.TarInfo(name=os.path.basename(dest_path))
            tarinfo.size = len(file_data)
            tarinfo.mtime = time.time()
            tar.addfile(tarinfo, io.BytesIO(file_data))
            
        tar_stream.seek(0)
        self.container.put_archive(os.path.dirname(dest_path), tar_stream)
        
    def read_file_from_container(self, filepath: str) -> str:
        """Reads a file from the container."""
        if not self.container:
            raise RuntimeError("Sandbox is not running.")
            
        try:
            exit_code, output = self.container.exec_run(f"cat {filepath}")
            if exit_code != 0:
                return f"Error reading file: {output.decode('utf-8')}"
            return output.decode('utf-8')
        except Exception as e:
            return f"Error reading file: {str(e)}"

    def write_file_in_container(self, filepath: str, content: str) -> str:
        """Writes content to a file in the container."""
        if not self.container:
            raise RuntimeError("Sandbox is not running.")
        
        try:
            # Create a simple script to write the file, avoiding quote escaping hell
            script = f"cat << 'EOF' > {filepath}\n{content}\nEOF"
            exit_code, output = self.container.exec_run(["sh", "-c", script])
            if exit_code != 0:
                 return f"Error writing file: {output.decode('utf-8')}"
            return "Successfully wrote file."
        except Exception as e:
            return f"Error writing file: {str(e)}"
