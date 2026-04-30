import os
import logging

logger = logging.getLogger(__name__)

def detect_base_image(build_dir: str) -> str:
    """Detect the appropriate base Docker image based on repo contents."""
    files = os.listdir(build_dir)

    if "package.json" in files:
        return "node:20-slim"
    if "requirements.txt" in files or "pyproject.toml" in files or "Pipfile" in files:
        return "python:3.12-slim"
    if "go.mod" in files:
        return "golang:1.22-slim"
    if "pom.xml" in files or "build.gradle" in files:
        return "eclipse-temurin:21-jdk-slim"
    if "Gemfile" in files:
        return "ruby:3.3-slim"
    if "composer.json" in files:
        return "php:8.3-cli"

    logger.warning("Could not detect tech stack, falling back to ubuntu:22.04")
    return "ubuntu:22.04"
