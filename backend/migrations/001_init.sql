-- Cinemate: начальная схема PostgreSQL 16
-- pgvector и таблицы эмбеддингов добавляются отдельной миграцией на этапе AI-модуля.

CREATE TABLE users(
  id            BIGSERIAL PRIMARY KEY,
  name          VARCHAR(60)  NOT NULL,
  email         VARCHAR(120) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','moderator','admin')),
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  legacy_user_id INT UNIQUE
);
CREATE UNIQUE INDEX users_email_lower_uq ON users (lower(email));

CREATE TABLE user_profiles(
  user_id      BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  display_name VARCHAR(60),
  avatar_url   TEXT,
  locale       VARCHAR(10) NOT NULL DEFAULT 'ru',
  timezone     VARCHAR(50) NOT NULL DEFAULT 'Europe/Moscow',
  settings     JSONB NOT NULL DEFAULT '{"notify_telegram":true,"notify_new_episodes":true,"remind_inactive_days":14}',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- «Пустая аналитика»: снимок считается по требованию и кэшируется здесь
CREATE TABLE user_stats(
  user_id    BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  data       JSONB NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE telegram_links(
  id          BIGSERIAL PRIMARY KEY,
  user_id     BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  telegram_id BIGINT NOT NULL UNIQUE,
  chat_id     BIGINT NOT NULL,
  username    VARCHAR(64),
  linked_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE link_codes(
  id                  BIGSERIAL PRIMARY KEY,
  user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash           CHAR(64) NOT NULL UNIQUE,      -- HMAC-SHA256, сам код не хранится
  expires_at          TIMESTAMPTZ NOT NULL,
  used_at             TIMESTAMPTZ,
  used_by_telegram_id BIGINT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX link_codes_user_idx ON link_codes(user_id, created_at DESC);

CREATE TABLE content_types(
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL
);
INSERT INTO content_types(code,name) VALUES
 ('movie','Фильм'),('series','Сериал'),('documentary','Документальный'),('cartoon','Мультфильм'),('anime','Аниме');

CREATE TABLE content_items(
  id              BIGSERIAL PRIMARY KEY,
  kinopoisk_id    BIGINT UNIQUE,
  imdb_id         VARCHAR(20) UNIQUE,
  tmdb_id         BIGINT,
  type_code       TEXT NOT NULL REFERENCES content_types(code) DEFAULT 'movie',
  is_serial       BOOLEAN NOT NULL DEFAULT FALSE,
  title           VARCHAR(300) NOT NULL,
  original_title  VARCHAR(300),
  year            SMALLINT CHECK (year IS NULL OR year BETWEEN 1888 AND 2100),
  description     TEXT,
  short_description TEXT,
  poster_url      TEXT,
  rating_kp       NUMERIC(3,1),
  rating_imdb     NUMERIC(3,1),
  duration_min    INT,
  total_episodes  INT NOT NULL DEFAULT 0,
  countries       TEXT[] NOT NULL DEFAULT '{}',
  age_rating      SMALLINT,
  watchability    JSONB NOT NULL DEFAULT '[]',     -- [{name,url,logo}] — легальные стриминги
  created_by      BIGINT REFERENCES users(id) ON DELETE SET NULL, -- для ручных записей без Кинопоиска
  fetched_at      TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  legacy_title_id INT UNIQUE
);
CREATE INDEX content_items_title_idx ON content_items (lower(title));
CREATE INDEX content_items_year_idx ON content_items (year);
CREATE INDEX content_items_fts_idx ON content_items
  USING GIN (to_tsvector('russian', coalesce(title,'')||' '||coalesce(original_title,'')||' '||coalesce(description,'')));

CREATE TABLE genres(
  id   SERIAL PRIMARY KEY,
  name VARCHAR(80) NOT NULL UNIQUE
);
CREATE TABLE content_genres(
  content_id BIGINT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  genre_id   INT    NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
  PRIMARY KEY (content_id, genre_id)
);
CREATE INDEX content_genres_genre_idx ON content_genres(genre_id);

CREATE TABLE people(
  id           BIGSERIAL PRIMARY KEY,
  kinopoisk_id BIGINT UNIQUE,
  name         VARCHAR(200) NOT NULL,
  en_name      VARCHAR(200),
  photo_url    TEXT
);
CREATE UNIQUE INDEX people_legacy_name_uq ON people (lower(name)) WHERE kinopoisk_id IS NULL;

CREATE TABLE content_people(
  content_id BIGINT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  person_id  BIGINT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK (role IN ('director','actor','writer','producer','other')),
  sort_order INT NOT NULL DEFAULT 0,
  PRIMARY KEY (content_id, person_id, role)
);
CREATE INDEX content_people_person_idx ON content_people(person_id, role);

CREATE TABLE seasons(
  id             BIGSERIAL PRIMARY KEY,
  content_id     BIGINT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  number         SMALLINT NOT NULL,
  episodes_count INT NOT NULL DEFAULT 0,
  legacy_season_id INT UNIQUE,
  UNIQUE (content_id, number)
);
CREATE TABLE episodes(
  id           BIGSERIAL PRIMARY KEY,
  season_id    BIGINT NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  number       SMALLINT NOT NULL,
  name         VARCHAR(300) NOT NULL DEFAULT '',
  air_date     DATE,
  duration_min INT,
  legacy_episode_id INT UNIQUE,
  UNIQUE (season_id, number)
);

CREATE TABLE user_statuses(
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code       TEXT NOT NULL CHECK (code IN ('plan','watching','watched','dropped','later')),
  name       VARCHAR(40) NOT NULL,
  sort_order SMALLINT NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, code)
);

CREATE TABLE user_content(
  id           BIGSERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  content_id   BIGINT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  status_code  TEXT NOT NULL DEFAULT 'plan',
  watched_eps  INT NOT NULL DEFAULT 0,
  plan_date    DATE,
  visibility   TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','shared','public')),
  added_via    TEXT NOT NULL DEFAULT 'web' CHECK (added_via IN ('web','telegram','import','migration')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, content_id),
  FOREIGN KEY (user_id, status_code) REFERENCES user_statuses(user_id, code)
);
CREATE INDEX user_content_status_idx ON user_content(user_id, status_code);
CREATE INDEX user_content_public_idx ON user_content(visibility) WHERE visibility = 'public';

-- Где хранится: у одной записи может быть несколько источников
CREATE TABLE content_sources(
  id              BIGSERIAL PRIMARY KEY,
  user_content_id BIGINT NOT NULL REFERENCES user_content(id) ON DELETE CASCADE,
  source_type     TEXT NOT NULL CHECK (source_type IN ('streaming','local','physical','other')),
  service_name    VARCHAR(80),
  url             TEXT,
  file_path       TEXT,
  file_size_bytes BIGINT,
  file_format     VARCHAR(20),
  media_kind      VARCHAR(30),
  storage_place   VARCHAR(200),
  note            TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX content_sources_uc_idx ON content_sources(user_content_id);

CREATE TABLE user_episodes(
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  episode_id BIGINT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  watched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, episode_id)
);

CREATE TABLE ratings(
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  content_id BIGINT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  stars      SMALLINT NOT NULL CHECK (stars BETWEEN 1 AND 5),
  legacy_rating10 NUMERIC(3,1),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, content_id)
);
CREATE TABLE reviews(
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  content_id BIGINT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  body       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, content_id)
);

CREATE TABLE collections(
  id          BIGSERIAL PRIMARY KEY,
  owner_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        VARCHAR(120) NOT NULL,
  description TEXT,
  visibility  TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','shared','public')),
  system_code TEXT CHECK (system_code IN ('want','watching','watched','favorites')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  legacy_collection_id INT UNIQUE,
  UNIQUE (owner_id, system_code)
);
CREATE INDEX collections_vis_idx ON collections(visibility);

CREATE TABLE collection_members(
  collection_id BIGINT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  member_role   TEXT NOT NULL DEFAULT 'viewer' CHECK (member_role IN ('viewer','editor')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (collection_id, user_id)
);
CREATE TABLE collection_items(
  collection_id BIGINT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  content_id    BIGINT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  added_by      BIGINT REFERENCES users(id) ON DELETE SET NULL,
  added_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (collection_id, content_id)
);

CREATE TABLE viewing_history(
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  content_id BIGINT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  episode_id BIGINT REFERENCES episodes(id) ON DELETE SET NULL,
  watched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  minutes    INT NOT NULL DEFAULT 0,
  legacy_history_id INT UNIQUE
);
CREATE INDEX viewing_history_user_idx ON viewing_history(user_id, watched_at);

CREATE TABLE recommendations(
  id          BIGSERIAL PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  query_text  TEXT NOT NULL,
  parsed      JSONB NOT NULL DEFAULT '{}',
  content_id  BIGINT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  score       REAL NOT NULL DEFAULT 0,
  explanation TEXT,
  used_llm    BOOLEAN NOT NULL DEFAULT FALSE,
  feedback    SMALLINT CHECK (feedback IN (-1,1)),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX recommendations_user_idx ON recommendations(user_id, created_at DESC);

CREATE TABLE notifications(
  id           BIGSERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind         TEXT NOT NULL CHECK (kind IN ('planned','inactive','new_episode','system')),
  channel      TEXT NOT NULL DEFAULT 'telegram' CHECK (channel IN ('telegram','web')),
  content_id   BIGINT REFERENCES content_items(id) ON DELETE CASCADE,
  payload      JSONB NOT NULL DEFAULT '{}',
  scheduled_at TIMESTAMPTZ NOT NULL,
  sent_at      TIMESTAMPTZ,
  status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','done','failed','cancelled')),
  legacy_reminder_id INT UNIQUE
);
CREATE INDEX notifications_due_idx ON notifications(scheduled_at) WHERE status = 'pending';

CREATE TABLE api_cache(
  cache_key  TEXT PRIMARY KEY,
  value      JSONB NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX api_cache_exp_idx ON api_cache(expires_at);

CREATE TABLE audit_log(
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT REFERENCES users(id) ON DELETE SET NULL,
  action     VARCHAR(60) NOT NULL,
  entity     VARCHAR(40),
  entity_id  BIGINT,
  meta       JSONB NOT NULL DEFAULT '{}',
  ip         INET,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_user_idx ON audit_log(user_id, created_at DESC);

CREATE TABLE login_attempts(
  id         BIGSERIAL PRIMARY KEY,
  k          VARCHAR(100) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX login_attempts_idx ON login_attempts(k, created_at);

-- Идемпотентно создаёт профиль, статусы, системные коллекции, настройки и пустую аналитику.
CREATE OR REPLACE FUNCTION bootstrap_user(p_user BIGINT) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO user_profiles(user_id, display_name)
    SELECT id, name FROM users WHERE id = p_user
    ON CONFLICT (user_id) DO NOTHING;
  INSERT INTO user_stats(user_id) VALUES (p_user) ON CONFLICT (user_id) DO NOTHING;
  INSERT INTO user_statuses(user_id, code, name, sort_order) VALUES
    (p_user,'plan','В планах',1),(p_user,'watching','В процессе',2),(p_user,'watched','Просмотрено',3),
    (p_user,'dropped','Брошено',4),(p_user,'later','Отложено',5)
    ON CONFLICT (user_id, code) DO NOTHING;
  INSERT INTO collections(owner_id, name, description, visibility, system_code) VALUES
    (p_user,'Хочу посмотреть','Системная коллекция: статус «В планах»','private','want'),
    (p_user,'Смотрю','Системная коллекция: статус «В процессе»','private','watching'),
    (p_user,'Просмотрено','Системная коллекция: статус «Просмотрено»','private','watched'),
    (p_user,'Избранное','Системная коллекция','private','favorites')
    ON CONFLICT (owner_id, system_code) DO NOTHING;
END $$;

-- Приводит системные коллекции статусов в соответствие со статусами записей.
CREATE OR REPLACE FUNCTION sync_status_collections(p_user BIGINT, p_content BIGINT DEFAULT NULL)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM collection_items ci USING collections c, user_content uc
   WHERE ci.collection_id = c.id AND c.owner_id = p_user
     AND c.system_code IN ('want','watching','watched')
     AND (p_content IS NULL OR ci.content_id = p_content)
     AND uc.user_id = p_user AND uc.content_id = ci.content_id
     AND c.system_code IS DISTINCT FROM
         (CASE uc.status_code WHEN 'plan' THEN 'want' WHEN 'watching' THEN 'watching' WHEN 'watched' THEN 'watched' END);
  INSERT INTO collection_items(collection_id, content_id, added_by)
  SELECT c.id, uc.content_id, p_user
    FROM user_content uc
    JOIN collections c ON c.owner_id = p_user AND c.system_code =
         (CASE uc.status_code WHEN 'plan' THEN 'want' WHEN 'watching' THEN 'watching' WHEN 'watched' THEN 'watched' END)
   WHERE uc.user_id = p_user AND (p_content IS NULL OR uc.content_id = p_content)
  ON CONFLICT DO NOTHING;
END $$;
