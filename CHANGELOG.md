# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased


### Changed
  - Complete refactor of application structure: core app now defines
    all base classes, and each ethereum/raiden integration are
    implemented as django apps that depend on core
  - ethereum (tasks): RPC providers for rollups/sidechains do not
    need to rely on peer count to determine if it is online
  - tokens are not listed by default. Hub Operators need to
    list them through the admin
  - only shows listed tokens (the ones approved by operator)
  - deposit/payment order: routes are no longer created automatically.
  - checkout: Checkout instance points to payment order (instead of
    deriving from it)
  - information on "network" endpoints is now generalized to all
    payment networks: ethereum/raiden
  - background processes do not index all transactions from the
    blockchain, it just goes back in some point in history (default
    5000 blocks) and then just listens to new blocks
  - events websocket is now public and should be used exclusively to
    send public messages about network events.
  - messages about deposit on networks now carry only identifiers, such as
    Deposit id / payment id.

### Added

  - admin: new filters for list of tokens
  - admin: new filters for list of stable tokens
  - admin: actions to list/de-list tokens
  - admin: new filter for listing chains (active providers only)
  - checkout (API): added endpoint to create new route from checkout
  - payment order (models): add "reference" field
  - command `run_payment_processors` to listen to all open payment routes.

### Removed
  - Raiden (API): Removed channel/UDC management endpoints. Operators
    should connect directly to node and use its API and/or the Web UI.
  - Raiden (models): removed tracking of Channel Events on TokenNetworks.
  - erc20 (API): users are no longer able to add new tokens (potential
    security risk)
  - erc20 (API): removed "listed" filter from token list endpoint.
  - checkout: removed external_identifier field, as it is serving the
    same purpose as payment order "reference"
  - admin: removed "internal apps" (celery tasks, groups, etc). Admin
    site is meant to be used by operators.

### Fixed
  - Avoid celery flooding task server with periodic tasks
  - tokenlist.org schema definition: polygon chain uses long tags,
    increased MaxLength


## [0.4.2] - 2022-03-25

### Added
 - API Endpoint to list Token Networks, optionally filtered by chain
   and/or if we have a channel connection to it.


### Changed

 - Refactored transfer model, broken from single Transfer class into
   Internal/Blockchain/Raiden transfers, and corresponding
   execution/confirmation models

 - Raiden operations (channel funding, User Deposit funding,
   joining/leaving token network) are done through the Raiden Node and
   the celery tasks are tracked. The results are stored on the
   database.

 - All event processors that worked with asyncio have been changed
   into traditional management commands. The `run_event_streams`
   command was renamed to `run_stream_processor` and takes one single
   callable name as a parameter.


## [0.4.0] - 2022-01-31

### Added

 - Support for connections with multiple chains
 - Support for connections with multiple raiden nodes
 - Blockchain endpoint status now provide information about estimated
   gas fees
 - Ability for hub operators to import [token
   lists](https://tokenlists.org)
 - Ability for users to define which users they want to track
 - Faceted / Filtered search for tokens
 - API endpoints to provide meta-data about any token (whether is a
   stable token or not, if it is wrapper for another contract) and
   current information in relation to the blockchain status (cost to
   make a transfer)

### Changed
 - Improved process that listens and handles blockchain events.
   Instead of each function making as many queries as needed, there is
   now only one main process listening to blockchain events that
   notifies of every new block, and the handlers only make further
   requests if the transaction data indicates that it is relevant to
   the hub.

### Removed
 - Site-wide definition of tracked tokens
