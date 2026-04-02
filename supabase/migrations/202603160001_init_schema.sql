-- LMS baseline schema
create extension if not exists pgcrypto;

create table if not exists teams (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  current_elo numeric(8,2) not null default 1500,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists fixtures (
  id uuid primary key default gen_random_uuid(),
  gameweek integer not null,
  home_team_id uuid not null references teams(id) on delete restrict,
  away_team_id uuid not null references teams(id) on delete restrict,
  kickoff timestamptz not null,
  status text not null default 'scheduled',
  created_at timestamptz not null default now(),
  check (home_team_id <> away_team_id)
);

create table if not exists odds (
  id uuid primary key default gen_random_uuid(),
  fixture_id uuid not null references fixtures(id) on delete cascade,
  bookmaker text not null,
  raw_h numeric(10,4) not null,
  raw_d numeric(10,4) not null,
  raw_a numeric(10,4) not null,
  de_vigged_win_prob numeric(8,6),
  captured_at timestamptz not null default now()
);

create table if not exists user_selections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  gameweek integer not null,
  team_id uuid not null references teams(id) on delete restrict,
  result text,
  created_at timestamptz not null default now(),
  unique (user_id, gameweek)
);

create index if not exists idx_fixtures_gameweek on fixtures(gameweek);
create index if not exists idx_odds_fixture_id on odds(fixture_id);
create index if not exists idx_user_selections_user_id on user_selections(user_id);

alter table teams enable row level security;
alter table fixtures enable row level security;
alter table odds enable row level security;
alter table user_selections enable row level security;

-- Public read for model outputs and fixtures.
drop policy if exists "Public can read teams" on teams;
create policy "Public can read teams"
  on teams for select
  using (true);

drop policy if exists "Public can read fixtures" on fixtures;
create policy "Public can read fixtures"
  on fixtures for select
  using (true);

drop policy if exists "Public can read odds" on odds;
create policy "Public can read odds"
  on odds for select
  using (true);

-- Users can only manage their own selections.
drop policy if exists "Users can read own selections" on user_selections;
create policy "Users can read own selections"
  on user_selections for select
  using (auth.uid() = user_id);

drop policy if exists "Users can insert own selections" on user_selections;
create policy "Users can insert own selections"
  on user_selections for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users can update own selections" on user_selections;
create policy "Users can update own selections"
  on user_selections for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
