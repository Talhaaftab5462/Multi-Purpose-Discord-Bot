# Discord Bot with Counting Game and Moderation Features

A feature-rich Discord bot that includes a counting game, moderation tools, and various utility commands. The bot is built using discord.py and uses PostgreSQL for data persistence.

## Features

### Counting Game
- Interactive counting game with save system
- Anti-spam measures and lockout system
- Bad counter role assignment for frequent mistakes
- Daily save collection system
- Save decay for inactive users
- Record tracking for highest count achieved

### Booster Management
- Automatic booster role assignment
- Manual booster role management commands
- Booster listing functionality

### Moderation & Logging
- Message deletion logging with media preservation
- Reaction tracking (add/remove)
- Excessive ping detection and logging
- Media attachment caching

### Utility Commands
- Bot status and health monitoring
- Server statistics
- System resource usage tracking
- Error logging

## Environment Variables

The bot requires the following environment variables to be set:

```env
DISCORD_TOKEN=your_bot_token
DATABASE_URL=your_postgresql_connection_string
EXTRA_BOOSTER_ROLE_ID=role_id
PING_LIMIT=number_of_pings
TIME_FRAME=time_in_seconds
PING_CHANNEL_LOGGING_ID=channel_id
LOGGING_CHANNEL_ID=channel_id
REACTION_LOG_CHANNEL_ID=channel_id
COUNT_LOG_CHANNEL_ID=channel_id
BAD_COUNTER_ROLE_ID=role_id
COUNTDOWN_CHANNEL_ID=channel_id
MUTED_ROLE_ID=role_id
```

## Game Configuration

The counting game can be configured through environment variables:

```env
SAVE_LIMIT=maximum_saves
SAVE_COOLDOWN_HOURS=hours_between_saves
DECAY_DAYS=days_until_save_decay
LOCKOUT_HOURS=hours_of_lockout
LOCKOUT_LIMIT=lockouts_before_bad_counter_role
```

## Commands

### Slash Commands
- `/count_channel` - Set the counting game channel (Admin only)
- `/collectsave` - Collect your daily save
- `/save` - Check your current number of saves
- `/count_record` - Display the highest count achieved
- `/ping` - Check bot status and health
- `/listboosters` - List all server boosters

## Database Schema

### user_data Table
```sql
CREATE TABLE user_data (
    user_id BIGINT PRIMARY KEY,
    saves INTEGER NOT NULL,
    last_collected TIMESTAMP NOT NULL,
    locked_until TIMESTAMP,
    lockout_count INTEGER NOT NULL
);
```

### global_state Table
```sql
CREATE TABLE global_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

## Features in Detail

### Counting Game
- Players take turns counting numbers in sequence
- Players can collect daily saves to prevent count resets
- Saves decay after a period of inactivity
- Players get locked out after making mistakes
- Frequent mistakes result in a "bad counter" role

### Booster System
- Automatic role assignment for server boosters
- Manual role management through commands
- Booster listing functionality
- Integration with server mute system

### Logging System
- Comprehensive message deletion logging
- Media attachment preservation
- Reaction tracking
- Excessive ping detection
- System health monitoring

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install discord.py asyncpg python-dotenv
   ```
3. Set up PostgreSQL database
4. Configure environment variables
5. Run the bot:
   ```bash
   python bot.py
   ```

## Dependencies

- discord.py
- asyncpg
- python-dotenv
- psutil
- dateutil

## Contributing

Feel free to submit issues and enhancement requests! 
