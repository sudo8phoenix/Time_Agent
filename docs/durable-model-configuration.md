# Durable model configuration

New report runs and conversation tasks record model/provider/key-slot assignments,
prompt version, timeouts and the Groq account-policy flag. V1 report runs also
record their baseline model assignment. Credentials remain in secret settings.

The version-2 source contract hashes all application Python files, the generated
extraction schema, Python/dependency versions and the Ollama endpoint identity.
The endpoint is hashed rather than stored as a potentially credential-bearing URL.
Generation defaults and other schema builders are protected by source/dependency
identity. Changed code, dependencies, schema or endpoint stops a resume. This is
conservative: even a comment edit requires restoring the pinned build or reviewed
migration. Role/model/timeout defaults are read from the retained assignment.

Unpinned legacy work stops before a new model call; it is not silently backfilled.
Completed report records can be read/replayed without new inference. Restore the
pinned build or prepare a reviewed migration retaining original identities,
counters, deadlines, checkpoints and prior failures. Do not overwrite the stored
contract with the current hash just to bypass the guard. No automatic legacy
migration or production restart was performed in batch 32.

See [testing and quality](TESTING_AND_QUALITY.md) for verification and limitations.
