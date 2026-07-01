# mycard-subscriptions Specification

## Purpose

Define the implemented MyCard subscription, unsubscription, polling, cache, and match-notification behavior.

## Requirements

### Requirement: MyCard match subscription

The system SHALL allow users or groups to subscribe to a MyCard user's newest match notifications.

#### Scenario: User subscribes with explicit username

- **GIVEN** a user sends `订阅 <username>`
- **WHEN** the MyCard user has a latest arena record
- **THEN** the bot stores the subscription in `data/subscribe.json`
- **AND** initializes `data/last_match.json` for that username when no cache entry exists
- **AND** replies `订阅成功：<username>`

#### Scenario: User subscribes without username

- **GIVEN** a user sends `订阅` without a username
- **THEN** the bot uses the sender's bound MyCard username
- **OR** asks the sender to bind or provide a MyCard username

#### Scenario: Subscription is created in a group

- **GIVEN** the subscription command is sent in a group
- **THEN** the subscription target is stored as `["group", "<group id>"]`

#### Scenario: Subscription is created outside a group

- **GIVEN** the subscription command is not sent in a group
- **THEN** the subscription target is stored as `["private", "<user id>"]`

### Requirement: MyCard match unsubscription

The system SHALL allow users or groups to remove a MyCard match subscription.

#### Scenario: User unsubscribes

- **GIVEN** a user sends `退订 <username>`
- **THEN** the bot removes the current group or private target from that username's subscription list
- **AND** deletes the username entry when no targets remain
- **AND** replies whether unsubscription succeeded

#### Scenario: User unsubscribes without username

- **GIVEN** a user sends `退订` without a username
- **THEN** the bot uses the sender's bound MyCard username
- **OR** asks the sender to bind or provide a MyCard username

### Requirement: Scheduled subscription polling

The system SHALL poll subscribed MyCard users for new matches.

#### Scenario: Scheduler runs

- **GIVEN** `nonebot_plugin_apscheduler` is loaded
- **THEN** the job `mycard_subscribe_checker` runs every 60 seconds

#### Scenario: No subscriptions exist

- **GIVEN** `data/subscribe.json` has no subscriptions
- **WHEN** the scheduled job runs
- **THEN** the job returns without sending messages

#### Scenario: Latest match changes

- **GIVEN** a subscribed username has a latest MyCard record
- **AND** the latest record key differs from `data/last_match.json`
- **THEN** the bot updates the cached key
- **AND** sends a formatted match notification to each stored target

#### Scenario: Latest match is unchanged

- **GIVEN** a subscribed username has a latest MyCard record
- **AND** the latest record key equals the cached key
- **THEN** the bot sends no notification for that username

### Requirement: Match notification formatting

The system SHALL format MyCard match notifications with match participants, result, winner, score delta, and time.

#### Scenario: Match notification is sent

- **GIVEN** a new match record is detected
- **THEN** the message starts with `MyCard 新对局`
- **AND** includes player, matchup, result, winner, before/after score, and time converted to Asia/Shanghai when possible

## Open Questions

- The repository does not define expected behavior when one target repeatedly fails to receive notifications.
- The repository does not define whether subscriptions should be permission-scoped, rate-limited, or owner-managed.
