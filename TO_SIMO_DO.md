# Manual Actions

- Set `MODEL` in `backend/.env` to a live Regolo/Mistral model id that supports tool/function calling before testing ambiguous LLM-routed questions. The current env loads the LLM base URL and API key, but `MODEL` is still empty.
