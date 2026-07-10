import pytest
from agent47.domain.apikey.service import validate_key_format

def test_validate_key_format_valid():
    # Masked keys should always pass
    validate_key_format("openrouter", "sk-or-v1-...1234")
    validate_key_format("google", "AIzaSy...abcd")
    validate_key_format("openai", "sk-proj-...xyz")
    
    # Valid key formats
    validate_key_format("openrouter", "sk-or-v1-my-secret-openrouter-key")
    validate_key_format("google", "AIzaSyMyGoogleApiKey12345")
    validate_key_format("anthropic", "sk-ant-sid-anthropic-key-value")
    validate_key_format("openai", "sk-proj-my-openai-key-value")
    validate_key_format("openai", "sk-older-openai-style-key")
    validate_key_format("groq", "gsk_groq_api_key_12345")

def test_validate_key_format_invalid():
    # Invalid OpenRouter
    with pytest.raises(ValueError, match="Invalid OpenRouter key format"):
        validate_key_format("openrouter", "sk-my-invalid-key")
        
    # Invalid Google
    with pytest.raises(ValueError, match="Invalid Google API key format"):
        validate_key_format("google", "sk-proj-not-google")
        
    # Invalid Anthropic
    with pytest.raises(ValueError, match="Invalid Anthropic API key format"):
        validate_key_format("anthropic", "AIzaSy-not-anthropic")
        
    # Invalid OpenAI
    with pytest.raises(ValueError, match="Invalid OpenAI API key format"):
        validate_key_format("openai", "gsk_not-openai")
        
    # Invalid Groq
    with pytest.raises(ValueError, match="Invalid Groq API key format"):
        validate_key_format("groq", "sk-ant-not-groq")
