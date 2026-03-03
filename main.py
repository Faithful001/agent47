"""
Agent47: A multi-agent system for autonomous bug fixing
in isolated Docker sandbox environments.

Entry point for the application.
"""

from src.config import basic_model, advanced_model


if __name__ == "__main__":
    print("Agent47 initialized.")
    print(f"Handler model: {basic_model.model_name}")
    print(f"Operative model: {advanced_model.model_name}")
