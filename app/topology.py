from dataclasses import dataclass


@dataclass(frozen=True)
class AeDefinition:
    containers: tuple[str, ...]


MOBIUS_TOPOLOGY: dict[str, AeDefinition] = {
    "postureCamera": AeDefinition(("command", "status", "postureSamples", "postureEvents")),
    "deskInterface": AeDefinition(("lcdCommand", "buttonEvents", "status")),
    "deskMotor": AeDefinition(("command", "status", "motorEvents")),
    "postureLight": AeDefinition(("command", "status", "lightEvents")),
    "analyticsServer": AeDefinition(
        ("status", "sessionEvents", "currentSession", "suggestions", "sessionSummaries")
    ),
}

# Containers whose content instances must notify analyticsServer.
SUBSCRIPTION_SOURCES: tuple[tuple[str, str], ...] = (
    ("postureCamera", "status"),
    ("postureCamera", "postureSamples"),
    ("postureCamera", "postureEvents"),
    ("deskInterface", "buttonEvents"),
    ("deskInterface", "status"),
    ("deskMotor", "status"),
    ("deskMotor", "motorEvents"),
    ("postureLight", "status"),
    ("postureLight", "lightEvents"),
)

COMMAND_TARGETS: dict[str, tuple[str, str]] = {
    "posture-camera": ("postureCamera", "command"),
    "desk-interface": ("deskInterface", "lcdCommand"),
    "desk-motor": ("deskMotor", "command"),
    "posture-light": ("postureLight", "command"),
}

ANALYTICS_AE = "analyticsServer"

