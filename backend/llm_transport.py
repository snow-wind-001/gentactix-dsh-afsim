"""Per-launch native DSH transport configuration; contains no credentials.

Keep the existing provider route ID so stored DSH sessions remain resumable.
OpenAI-compatible servers must not inherit DeepSeek Messages' effort enum.
"""
import os
from urllib.parse import urlsplit


def provider_overlay(base_url, model, context_window, max_tokens):
    endpoint = urlsplit(base_url)
    if endpoint.hostname == 'api.deepseek.com' or endpoint.path.rstrip('/').endswith('/anthropic'):
        return []
    efforts = {level: level for level in ('low', 'medium', 'high', 'xhigh')}
    if os.environ.get('GENTACTIX_STRATA_COMPAT') == '1':
        efforts = {'low': 'low', 'medium': 'low', 'high': 'high', 'xhigh': 'max'}
    return [
        {'id': 'llm-deepseek', 'disabled': True},
        {'insert': [{
            'id': 'gentactix-openai-transport',
            'name': '@deepseek-ai/dsh-llm-pi-ai',
            'config': {'providers': {'deepseek-official': {
                'displayName': 'GenTactix OpenAI-compatible',
                'apiKeyEnv': 'DEEPSEEK_API_KEY',
                'api': 'openai-completions',
                'baseURL': base_url,
                'defaultContextWindow': context_window,
                'defaultMaxTokens': max_tokens,
                'compat': {
                    'maxTokensField': 'max_tokens',
                    'supportsStore': False,
                    'supportsDeveloperRole': False,
                    'supportsReasoningEffort': True,
                    'thinkingFormat': 'openai',
                },
                'models': [{
                    'id': model, 'contextWindow': context_window, 'maxTokens': max_tokens,
                    'input': ['text'],
                    'reasoningEfforts': efforts,
                }],
            }}},
        }]},
    ]
