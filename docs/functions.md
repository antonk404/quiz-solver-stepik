# Функции и методы проекта

Краткая справка по функциям/методам (1-3 строки на пункт).

## `src/main.py`
- `main()` - точка входа пайплайна: читает настройки, валидирует URL курса, поднимает клиентов и запускает обработку курса.

## `src/logging_config.py`
- `setup_logging()` - настраивает формат и уровень root-логгера, а также снижает шум от сторонних библиотек.

## `src/config.py`
- `Settings.validate_ai_provider_settings()` - нормализует `AI_PROVIDER` и проверяет, что для выбранного режима заданы нужные API-ключи.

## `src/retry_utils.py`
- `_contains_any(text, tokens)` - проверяет, содержит ли строка хотя бы один маркер из набора.
- `_extract_retry_delay_seconds(error_text)` - извлекает server-side `retryDelay` из текста ошибки, если он есть.
- `is_retriable_api_error(exc)` - определяет, стоит ли ретраить ошибку Gemini API (только транзиентные).
- `_api_wait_seconds(retry_state)` - рассчитывает backoff с учетом fast/normal режима и подсказки сервера.

## `src/validation_utils.py`
- `validate_selected_indices(selected_indices, options_count, exc_type=...)` - валидирует индексы для choice-задач: не пусто, без дублей, в допустимом диапазоне.
- `validate_ordered_indices(ordered_indices, items_count, exc_type=...)` - проверяет, что порядок индексов является полной перестановкой `0..N-1`.

## `src/ai_client.py`
- `_is_groq_transient(exc)` - классифицирует ошибки Groq, которые безопасно ретраить (connection/5xx/529).
- `_retry_groq(fn)` - fallback-декоратор без ретраев, если пакет `groq` не установлен.
- `AIClient.__init__(...)` - инициализирует провайдеры, модели, safety-настройки и проверяет базовую конфигурацию.
- `AIClient._init_groq()` - поднимает Groq-клиент и список fallback-моделей, либо отключает Groq при отсутствии ключа/SDK.
- `AIClient._get_model_sequence()` - строит порядок попыток `(provider, model)` в зависимости от `AI_PROVIDER` и доступности клиентов.
- `AIClient._parse_model_candidates(raw_models)` - парсит строку с моделями (через `, ; \n`) в очищенный список без дублей.
- `AIClient._validate_inputs(question, options)` - валидирует входные данные для choice-задач.
- `AIClient._validate_selected_indices(indices, cnt)` - проксирует валидацию выбранных индексов с типом исключения AI-слоя.
- `AIClient._validate_ordered_indices(indices, cnt)` - проксирует валидацию ordered-индексов с ошибкой AI-слоя.
- `AIClient._build_reask_block(feedback)` - формирует блок prompt-а для повторной попытки после невалидного ответа.
- `AIClient._format_reask_reason(exc)` - переводит исключение в короткий feedback для re-ask.
- `AIClient._build_choice_prompt(...)` - собирает prompt для choice-задачи с вариантами и feedback.
- `AIClient._build_ordering_prompt(...)` - собирает prompt для matching/sorting с левым/правым списком.
- `AIClient._build_string_prompt(...)` - собирает prompt для текстового ответа.
- `AIClient._build_api_error(exc)` - нормализует ошибки Gemini в понятные сообщения доменного уровня.
- `AIClient._build_groq_error(exc)` - нормализует ошибки Groq в доменные исключения.
- `AIClient._is_daily_quota_error(exc)` - определяет исчерпание дневной квоты Gemini.
- `AIClient._is_provider_quota_error(exc, provider)` - определяет квотные ошибки для конкретного провайдера.
- `AIClient._build_provider_error(exc, provider)` - маппит ошибку провайдера в итоговую `AIClientResponseError`-иерархию.
- `AIClient._request_json_gemini(prompt, model_name, schema)` - отправляет запрос в Gemini с `response_schema`, возвращает raw JSON.
- `AIClient._request_json_groq(prompt, model_name, schema)` - отправляет JSON-only запрос в Groq, добавляя schema hints в prompt.
- `AIClient._request_json(prompt, model_name, schema, provider)` - маршрутизирует запрос к нужному провайдеру.
- `AIClient._solve_loop(task_label, schema, prompt_fn, validate_fn, extract_result_fn)` - общий цикл решения: перебирает модели, делает re-ask, валидирует JSON и переключает fallback.
- `AIClient.solve_choice_task(question, options)` - решает задания с выбором вариантов.
- `AIClient.solve_ordering_task(question, left_items, right_items)` - решает matching/sorting в форме ordered-индексов.
- `AIClient.solve_string_task(question)` - решает текстовые/числовые задачи одним строковым ответом.

## `src/stepik/auth.py`
- `StepikAuth.__init__(...)` - сохраняет OAuth2-креды и параметры обновления токена.
- `StepikAuth.is_expired` - property: показывает, пора ли обновлять токен с учетом `refresh_margin`.
- `StepikAuth.get_token()` - возвращает актуальный токен, при необходимости запрашивает новый.
- `StepikAuth._fetch_token()` - выполняет OAuth2 password grant и обновляет `access_token` + TTL.

## `src/stepik/http_client.py`
- `_is_transient(exc)` - определяет, относится ли ошибка транспорта к временным.
- `StepikHTTPClient.__init__(auth)` - сохраняет auth-объект и готовит транспортный клиент.
- `StepikHTTPClient.__aenter__()` - открывает `aiohttp`-сессию с Bearer-токеном.
- `StepikHTTPClient.__aexit__(...)` - корректно закрывает HTTP-сессию.
- `StepikHTTPClient.session` - property: возвращает активную сессию или бросает ошибку, если клиент не активен.
- `StepikHTTPClient._refresh_if_needed()` - проверяет TTL токена и пересоздает сессию с новым токеном.
- `StepikHTTPClient._check_response(resp)` - переводит HTTP-статусы в типизированные исключения Stepik-слоя.
- `StepikHTTPClient.get(path, **kwargs)` - выполняет GET с автообновлением токена и retry на транзиентные ошибки.
- `StepikHTTPClient.post(path, json)` - выполняет POST с автообновлением токена и retry на транзиентные ошибки.

## `src/stepik/api_client.py`
- `StepikAPIClient.__init__(http)` - принимает транспорт и инициализирует кэш шагов урока.
- `StepikAPIClient.parse_url(url)` - проксирует парсинг URL шага в `parse_step_url`.
- `StepikAPIClient.get_step(step_id)` - загружает шаг и преобразует сырой API-ответ в `StepData`.
- `StepikAPIClient.get_lesson_step_ids(lesson_id)` - возвращает шаги урока, используя локальный кэш.
- `StepikAPIClient.resolve_step_id(lesson_id, position)` - переводит позицию шага в уроке в реальный `step_id`.
- `StepikAPIClient.create_attempt(step_id)` - создает попытку и возвращает `AttemptData`.
- `StepikAPIClient.submit_answer(attempt_id, reply)` - отправляет reply и возвращает `submission_id`.
- `StepikAPIClient.poll_status(submission_id, max_polls=20, delay=0.5)` - опрашивает статус проверки до финального состояния или таймаута.
- `StepikAPIClient.is_step_passed(step_id)` - проверяет, есть ли корректная отправка по шагу.
- `StepikAPIClient.get_course_steps(course_id)` - проходит структуру курса (sections -> units -> lessons -> steps) и собирает пары `(lesson_id, step_id)`.

## `src/stepik/reply_builders.py`
- `build_choice_reply(selected, total)` - строит `{"choices": [bool, ...]}` из списка выбранных индексов.
- `build_ordering_reply(ordering)` - строит reply для sorting/matching в формате `{"ordering": ...}`.
- `build_string_reply(answer)` - строит текстовый reply для string/free-answer задач.
- `build_number_reply(number)` - строит reply для number/math задач (число передается строкой).

## `src/stepik/utils.py`
- `strip_html(html)` - очищает HTML в человекочитаемый plain text.
- `parse_step_url(url)` - извлекает `lesson_id` и позицию шага из URL вида `/lesson/<id>/step/<n>`.
- `parse_course_id(url)` - извлекает `course_id` из URL курса.

## `src/stepik/solvers.py`
- `_find_option_index(target, options, used)` - ищет индекс опции (сначала точное, затем case-insensitive совпадение).
- `_build_correct_mapping(pairs)` - строит словарь правильных пар `term -> definition` из `source.pairs`.
- `_parse_matching_dataset(attempt)` - валидирует matching dataset и извлекает `(terms, options)`.
- `_match_terms_to_options(terms, options, correct)` - строит `ordering` по правильному маппингу и доступным опциям.
- `try_solve_matching(step, attempt)` - пытается решить matching программно, возвращает `ordering` или `None`.
- `_parse_sorting_dataset(attempt)` - извлекает перемешанные элементы sorting из dataset.
- `_build_sorting_order(correct_order, shuffled)` - вычисляет перестановку для приведения shuffled к правильному порядку.
- `try_solve_sorting(step, attempt)` - пытается решить sorting программно, возвращает `ordering` или `None`.

## `src/orchestration/solver_registry.py`
- `SolverRegistry.__init__()` - создает пустой реестр солверов.
- `SolverRegistry.register(block_type, solver)` - регистрирует солвер для типа шага.
- `SolverRegistry.register_many(mapping)` - массовая регистрация солверов.
- `SolverRegistry.get(block_type)` - возвращает солвер по типу, либо `None`.
- `SolverRegistry.has(block_type)` - проверяет наличие солвера по типу.
- `SolverRegistry.supported_types` - property: возвращает набор поддерживаемых типов заданий.
- `create_default_registry()` - создает стандартный набор солверов проекта.

## `src/orchestration/step_checker.py`
- `StepChecker.__init__(api)` - сохраняет API-клиент для проверок состояния шага.
- `StepChecker.resolve_step_id(parsed)` - получает `step_id` по `lesson_id` и позиции.
- `StepChecker.is_already_passed(step_id)` - проверяет, решен ли шаг ранее.
- `StepChecker.get_step(step_id)` - загружает полные данные шага.
- `StepChecker.should_skip(step)` - решает, пропускать ли шаг (например text/video).

## `src/orchestration/step_processor.py`
- `StepProcessor.__init__(ai, api, registry, ...)` - связывает AI, API и реестр солверов, задает лимиты попыток.
- `StepProcessor.process(step_id)` - основной pipeline обработки шага: pre-check, выбор солвера, попытки отправки ответа.
- `StepProcessor._attempt_loop(step_id, step, solver)` - цикл попыток: create attempt -> solve -> submit -> poll status с обработкой ошибок.

## `src/orchestration/course_processor.py`
- `CourseProcessor.__init__(step_processor)` - сохраняет обработчик отдельного шага.
- `CourseProcessor._api` - property: быстрый доступ к API через `StepProcessor`.
- `CourseProcessor._delay` - property: задержка между шагами, делегированная из `StepProcessor`.
- `CourseProcessor.process_course(course_id)` - обходит все шаги курса и считает количество успешно обработанных.

## `src/orchestration/solvers/base.py`
- `BaseSolver.solve(...)` - контракт солвера: получить `step/attempt`, вернуть reply-словарь для отправки.

## `src/orchestration/solvers/choice.py`
- `ChoiceSolver.solve(api, ai, step, attempt, previous_reply)` - решает choice: извлекает варианты, формирует prompt, отправляет AI и строит reply.
- `ChoiceSolver._extract_texts(raw_opts)` - приводит список опций (dict/str) к очищенному списку текстов.

## `src/orchestration/solvers/matching.py`
- `MatchingSolver.solve(api, ai, step, attempt, previous_reply)` - сначала пытается программное решение, затем fallback в AI для matching.
- `MatchingSolver._extract_lists(attempt)` - извлекает левый/правый список из dataset с fallback-логикой по полям.

## `src/orchestration/solvers/sorting.py`
- `SortingSolver.solve(api, ai, step, attempt, previous_reply)` - сначала пробует программное решение sorting, иначе запрашивает AI.
- `SortingSolver._extract_items(attempt)` - извлекает элементы sorting из dataset и очищает HTML.

## `src/orchestration/solvers/text.py`
- `TextSolver.solve(api, ai, step, attempt, previous_reply)` - решает string/number/free-answer задачи через AI и выбирает корректный формат reply.

## Сложные методы (расширенно)
- `AIClient._solve_loop(...)` - центральный оркестратор AI-запросов. Перебирает список моделей и провайдеров, при невалидном JSON формирует re-ask, а при квотных ошибках делает fallback на следующую модель. Метод также разделяет провайдерные ошибки (Gemini/Groq) и приводит их к единому доменному виду.
- `StepikAPIClient.get_course_steps(course_id)` - строит плоский список шагов курса через иерархию API (`courses -> sections -> units -> lessons -> steps`). Это главный метод навигации по структуре курса, от которого зависит полнота обхода.
- `StepProcessor._attempt_loop(...)` - реализует retry-логику на уровне бизнес-процесса: создание попытки, решение солвером, отправка, ожидание статуса и ветвление по результатам (`correct/wrong/evaluation/timeout`).
- `StepikHTTPClient.get(...)` и `StepikHTTPClient.post(...)` - транспорт с двумя уровнями устойчивости: tenacity-retry для транзиентных сбоев и принудительное обновление токена при 401.
- `try_solve_matching(...)` / `try_solve_sorting(...)` - deterministic-ветка без AI: валидирует dataset через Pydantic и пытается построить корректный `ordering`; при неполных данных возвращает `None` для fallback на AI.
