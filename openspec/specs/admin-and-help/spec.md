# admin-and-help Specification

## Purpose

Define the implemented help-image, superuser reload, and superuser liveness-test behavior.

## Requirements

### Requirement: Help image command

The system SHALL generate and send a help image.

#### Scenario: User requests help

- **GIVEN** a user sends `帮助`, `help`, or `菜单`
- **THEN** the bot ensures `assets/help.png` exists and is up to date with `assets/help.md`
- **AND** sends `assets/help.png` as a base64 OneBot image

#### Scenario: Help image is missing or stale

- **GIVEN** `assets/help.png` does not exist
- **OR** `assets/help.md` is newer than `assets/help.png`
- **WHEN** help is requested
- **THEN** the bot runs `assets/render_help.py` with the current Python executable
- **AND** uses the project root as the working directory
- **AND** applies a 20-second timeout

#### Scenario: Help generation fails

- **GIVEN** help image generation or reading fails
- **THEN** the bot replies with `帮助图生成失败：<error>`

### Requirement: Help renderer

The system SHALL render `assets/help.md` into `assets/help.png`.

#### Scenario: Renderer runs

- **GIVEN** `python assets/render_help.py` is executed
- **THEN** the renderer parses Markdown with table support
- **AND** renders headings, paragraphs, lists, and tables into a PNG image
- **AND** writes the image to `assets/help.png`

### Requirement: Superuser reload command

The system SHALL provide a superuser-only update/restart command.

#### Scenario: Superuser requests reload

- **GIVEN** a superuser sends `重载插件`, `更新代码`, `更新插件`, or `reload`
- **THEN** the bot runs `git pull` in the project root
- **AND** sends the last 1000 characters of Git output when pull succeeds
- **AND** starts `sudo systemctl restart kami-man` unless the command argument is `不重启`

#### Scenario: Superuser requests update without restart

- **GIVEN** a superuser sends the reload command with argument `不重启`
- **WHEN** `git pull` succeeds
- **THEN** the bot replies that code was updated but not restarted

#### Scenario: Git pull fails

- **GIVEN** the reload command runs
- **WHEN** `git pull` exits with a non-zero code
- **THEN** the bot replies with the Git output

#### Scenario: Git pull times out

- **GIVEN** the reload command runs
- **WHEN** `git pull` exceeds 60 seconds
- **THEN** the bot replies `Git 拉取超时。`

### Requirement: Superuser test command

The system SHALL provide a superuser-only bot liveness command.

#### Scenario: Superuser sends test command

- **GIVEN** a superuser sends `test`, `测试`, or `ping`
- **THEN** the bot replies `bot 正常运行`

## Open Questions

- The reload command name suggests plugin reload, but current behavior is repository pull plus optional systemd restart.
- The repository does not define behavior for non-Linux deployments using the reload command.
