import docker
import os
import tarfile
import io
import time

class Sandbox:
    def __init__(self, image="ubuntu:22.04"):
        self._client = None
        self.image = image
        self.container = None

    @property
    def client(self):
        """Lazily connect to Docker only when actually needed."""
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def start(self):
        """Starts a fresh docker container."""
        print(f"Starting sandbox with image {self.image}...")
        self.container = self.client.containers.run(
            self.image,
            detach=True,
            tty=True,
            command="tail -f /dev/null"  # Keep container alive
        )

        # Install common language runtimes and tools so the
        # Operative can work with any project type.
        self.execute_command(
            "apt-get update && apt-get install -y --no-install-recommends "
            "python3 python3-pip nodejs npm git curl build-essential"
        )
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
        
        # read the file at the src_path
        with open(src_path, "rb") as f:
            file_data = f.read()

        # prepare the archive
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            tarinfo = tarfile.TarInfo(name=os.path.basename(dest_path))
            tarinfo.size = len(file_data)
            tarinfo.mtime = time.time()
            tar.addfile(tarinfo, io.BytesIO(file_data))
        
        tar_stream.seek(0) # take the pointer back to the top

        self.container.put_archive(os.path.dirname(dest_path), tar_stream)

    def copy_repo_to_container(self, local_dir: str, container_dir: str):
        """Copy an entire local directory into the container.

        Creates a tar archive of `local_dir` and extracts it into
        `container_dir` inside the container.
        """
        if not self.container:
            raise RuntimeError("Sandbox is not running.")

        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            tar.add(local_dir, arcname=".")

        tar_stream.seek(0)
        self.execute_command(f"mkdir -p {container_dir}")
        self.container.put_archive(container_dir, tar_stream)
        
        
    def copy_repo_from_container(self, container_dir: str, local_dir: str):
        """Copy the workspace back from the container to the local directory.

        Extracts a tar archive of `container_dir` from the container and
        unpacks it into `local_dir`, overwriting existing files so that
        local changes match what the Operative modified inside the sandbox.
        """
        if not self.container:
            raise RuntimeError("Sandbox is not running.")

        bits, _ = self.container.get_archive(container_dir)

        tar_stream = io.BytesIO()
        for chunk in bits:
            tar_stream.write(chunk)
        tar_stream.seek(0)

        with tarfile.open(fileobj=tar_stream, mode="r") as tar:
            # The archive root is the basename of container_dir (e.g. "workspace").
            # We need to strip that top-level directory so files land directly in local_dir.
            prefix = os.path.basename(container_dir.rstrip("/")) + "/"
            for member in tar.getmembers():
                if member.name.startswith(prefix):
                    member.name = member.name[len(prefix):]
                elif member.name == prefix.rstrip("/"):
                    continue  # skip the root directory entry itself
                if member.name:  # skip empty names
                    tar.extract(member, local_dir)

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
