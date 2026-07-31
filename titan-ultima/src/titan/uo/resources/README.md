# Ultima Online metadata resources

This folder contains local packaged metadata caches used by `titan uo` commands.
The animation body-name cache is generated from client metadata and optional local
tooling/emulation repositories, then read at runtime through `importlib.resources`.

These resources are intended to make local installs useful without requiring the
same external source checkout paths on every machine. Review source licensing
before redistributing generated caches that include third-party or client-derived
metadata.
