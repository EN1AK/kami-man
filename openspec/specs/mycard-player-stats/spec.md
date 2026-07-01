# mycard-player-stats Specification

## Purpose

Define the implemented MyCard binding, binding lookup, battle-history statistics, win-rate statistics, and first-win query behavior.

## Requirements

### Requirement: MyCard username binding

The system SHALL allow a QQ user to bind their QQ user id to a MyCard username.

#### Scenario: User binds a username

- **GIVEN** a user sends `绑定 <username>`
- **THEN** the bot stores the mapping from QQ user id to `<username>` in `data/mycard_user.json`
- **AND** replies `绑定成功！`

#### Scenario: User omits username while binding

- **GIVEN** a user sends `绑定` without a username
- **THEN** the bot replies `请提供要绑定的用户名！`

### Requirement: Binding lookup

The system SHALL support looking up MyCard bindings.

#### Scenario: User queries own binding

- **GIVEN** a user sends `查询绑定` or `绑定查询`
- **THEN** the bot replies with that user's bound MyCard username when one exists
- **OR** replies that the user has not bound a MyCard username

#### Scenario: User queries mentioned user's binding

- **GIVEN** a user sends `查询绑定` or `绑定查询` with a QQ mention
- **THEN** the bot replies with the mentioned user's bound MyCard username when one exists
- **OR** replies that the mentioned user has not bound a MyCard username

#### Scenario: User reverse-queries a MyCard username

- **GIVEN** a user sends `查询绑定 <username>` or `绑定查询 <username>`
- **THEN** the bot replies with QQ users bound to that MyCard username
- **OR** replies that no user is bound to that MyCard username

### Requirement: Monthly history statistics

The system SHALL support monthly MyCard battle-history statistics.

#### Scenario: User queries monthly history

- **GIVEN** a user sends a message matching `历史`, `<month>月历史`, `<year>年<month>月历史`, or the same forms followed by a username
- **THEN** the bot fetches MyCard arena history for the resolved username
- **AND** filters records by `end_time` converted to Asia/Shanghai
- **AND** excludes zero-score-delta matches
- **AND** replies with player name, monthly valid match count, and monthly win rate

#### Scenario: Username is omitted

- **GIVEN** the history command omits username
- **WHEN** the message mentions a QQ user
- **THEN** the bot uses the mentioned user's binding
- **WHEN** the message has no usable mention
- **THEN** the bot uses the sender's binding

#### Scenario: Month or year is omitted

- **GIVEN** month is omitted
- **THEN** the bot uses the current local year and current local month
- **GIVEN** month is provided and year is omitted
- **THEN** the bot uses the current local year when the month is not later than the current local month
- **AND** otherwise uses the previous local year
- **GIVEN** a year below 2000 is provided
- **THEN** the bot adds 2000 to the year

#### Scenario: Monthly records exist

- **GIVEN** valid monthly records exist
- **THEN** the bot includes a matplotlib score chart image
- **AND** includes current score and current rank before monthly settlement
- **AND** includes settlement score and settlement rank after settlement

### Requirement: Win-rate statistics

The system SHALL support all-history MyCard win-rate statistics.

#### Scenario: User queries win rate

- **GIVEN** a user sends `胜率查询`, `胜率统计`, or either command followed by a username
- **THEN** the bot fetches MyCard arena history for the resolved username
- **AND** excludes zero-score-delta matches
- **AND** replies with total valid matches, total win rate, and count of months that have matches
- **AND** sends a matplotlib chart of monthly win rates when monthly data exists

### Requirement: First-win query

The system SHALL support MyCard first-win lookup.

#### Scenario: User queries first win

- **GIVEN** a user sends `首胜查询`, `首赢查询`, or either command followed by a username
- **THEN** the bot queries MyCard first-win status for the resolved username
- **AND** replies whether the user has completed today's first win

## External Dependencies

- MyCard data is fetched from `https://sapi.moecube.com:444/ygopro/`.
- The service paths used by current code are `arena/history`, `arena/user`, `arena/historyScore`, and `arena/firstwin`.

## Open Questions

- The repository does not define the full MyCard API response schema.
- The monthly settlement time is implemented as 22:00 Asia/Shanghai on the month's last day, but the business origin of that rule is not documented.
- The command parser uses local machine time for current year/month decisions; required deployment timezone is not documented.
