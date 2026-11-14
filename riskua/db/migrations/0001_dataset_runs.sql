-- Журнал завантажень наборів: що вантажили, з якого файла, скільки рядків, чим скінчилося.
-- Звідси команда /status бере свіжість наборів, а звіт — дату «станом на».
CREATE TABLE dataset_runs (
    id                 bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset            text        NOT NULL,
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz,
    -- running — іде; loaded — таблицю підмінено; unchanged — файл у джерелі не змінився;
    -- rejected — рядків менше за поріг, таблицю не підміняли; failed — помилка.
    status             text        NOT NULL
        CHECK (status IN ('running', 'loaded', 'unchanged', 'rejected', 'failed')),
    source_url         text,
    -- Дата файла в джерелі: від неї звіт пише «станом на».
    source_modified_at timestamptz,
    -- ETag або хеш файла: чи змінився файл від минулого завантаження.
    source_hash        text,
    row_count          bigint      CHECK (row_count >= 0),
    error              text
);

CREATE INDEX dataset_runs_dataset_started_idx ON dataset_runs (dataset, started_at DESC);
