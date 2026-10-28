"""Canonical skill vocabulary with aliases (Russian and English spellings).

Used to extract skills from resumes and vacancies and to compare them without false mismatches such as
"Postgres" vs "PostgreSQL". Unknown skills are still kept verbatim; the vocabulary only normalizes.
"""

import re
from functools import lru_cache

# canonical name -> aliases (lowercase). The canonical name itself is always an alias.
SKILLS: dict[str, list[str]] = {
    # Languages
    "Python": ["python3", "питон"],
    "JavaScript": ["js", "javascript", "ecmascript", "es6"],
    "TypeScript": ["ts", "typescript"],
    "Java": [],
    "Kotlin": [],
    "Go": ["golang"],
    "C#": ["c sharp", "csharp", ".net c#"],
    "C++": ["cpp", "c plus plus"],
    "C": [],
    "PHP": [],
    "Ruby": [],
    "Rust": [],
    "Swift": [],
    "SQL": ["sql"],
    "Bash": ["shell", "bash scripting", "shell scripting"],
    "PowerShell": ["powershell", "power shell"],
    "1С": ["1c", "1с:предприятие", "1c:enterprise"],
    # Backend / web
    "Django": ["django rest framework", "drf"],
    "FastAPI": ["fast api"],
    "Flask": [],
    "Node.js": ["nodejs"],
    "Express": ["express.js", "expressjs"],
    "NestJS": ["nest.js"],
    "Spring": ["spring boot", "spring framework"],
    "ASP.NET": ["asp.net core", ".net", "dotnet", ".net core"],
    "Laravel": [],
    "REST API": ["rest", "restful", "rest api", "restful api"],
    "GraphQL": [],
    "gRPC": ["grpc"],
    "Celery": [],
    "asyncio": ["asyncio"],
    "SQLAlchemy": [],
    "Pydantic": [],
    # Frontend
    "React": ["react.js", "reactjs"],
    "Next.js": ["nextjs"],
    "Vue.js": ["vue", "vuejs", "vue.js", "nuxt"],
    "Angular": [],
    "HTML": ["html5"],
    "CSS": ["css3", "scss", "sass", "less"],
    "Tailwind CSS": ["tailwind", "tailwindcss"],
    "Redux": [],
    # Data
    "PostgreSQL": ["postgres", "postgresql", "psql", "постгрес"],
    "MySQL": ["mariadb"],
    "MongoDB": ["mongo"],
    "Redis": [],
    "ClickHouse": ["clickhouse"],
    "Elasticsearch": ["elastic", "elk", "opensearch"],
    "Kafka": ["apache kafka"],
    "RabbitMQ": ["rabbit"],
    "Pandas": [],
    "NumPy": ["numpy"],
    "Excel": ["ms excel", "microsoft excel"],
    "Power BI": ["powerbi"],
    "Tableau": [],
    # AI / automation
    "Machine Learning": ["ml", "машинное обучение"],
    "Deep Learning": ["dl", "глубокое обучение"],
    "PyTorch": ["torch"],
    "TensorFlow": ["tf", "keras"],
    "scikit-learn": ["sklearn", "scikit learn"],
    "LLM": ["llm", "large language models", "большие языковые модели", "gpt", "chatgpt"],
    "Prompt Engineering": ["prompt engineering", "промпт-инжиниринг", "промпт инжиниринг", "промптинг"],
    "LangChain": ["langchain", "langgraph"],
    "RAG": ["retrieval augmented generation"],
    "NLP": ["обработка естественного языка", "natural language processing"],
    "Computer Vision": ["компьютерное зрение", "opencv"],
    "n8n": ["n8n"],
    "Make": ["make.com", "integromat"],
    "Zapier": [],
    "RPA": ["uipath", "pix rpa"],
    "Telegram Bot API": ["aiogram", "telegram bot", "телеграм бот", "telegram-бот", "python-telegram-bot"],
    "Web Scraping": ["парсинг", "scraping", "beautifulsoup", "scrapy", "selenium"],
    "API Integration": ["интеграции api", "api интеграции", "интеграция api", "webhooks"],
    # DevOps / sysadmin
    "Linux": ["ubuntu", "debian", "centos", "rhel", "astra linux", "линукс"],
    "Windows Server": ["windows server", "win server"],
    "Active Directory": ["ad", "active directory", "ldap", "gpo", "групповые политики"],
    "Docker": ["docker compose", "docker-compose"],
    "Kubernetes": ["k8s"],
    "Ansible": [],
    "Terraform": [],
    "CI/CD": ["ci/cd", "ci cd", "gitlab ci", "github actions", "jenkins"],
    "Git": ["github", "gitlab"],
    "Nginx": [],
    "Apache": ["apache http server", "httpd"],
    "Zabbix": [],
    "Prometheus": [],
    "Grafana": [],
    "Networking": ["tcp/ip", "компьютерные сети", "dns", "dhcp", "vlan", "маршрутизация"],
    "Cisco": ["ccna", "mikrotik"],
    "Virtualization": ["vmware", "hyper-v", "proxmox", "kvm", "виртуализация"],
    "Backup": ["резервное копирование", "veeam", "backup"],
    "Information Security": ["информационная безопасность", "иб"],
    "Helpdesk": ["техническая поддержка", "техподдержка", "service desk", "help desk", "helpdesk"],
    "ITIL": [],
    "Microsoft 365": ["office 365", "exchange", "ms office"],
    "AWS": ["amazon web services"],
    "Yandex Cloud": ["яндекс облако", "yandex.cloud"],
    # Design
    "Figma": ["фигма"],
    "UX Research": ["ux-исследования", "ux research", "пользовательские исследования", "custdev", "кастдев"],
    "UI Design": ["ui", "ui-дизайн", "ui design", "интерфейсы"],
    "UX Design": ["ux", "ux-дизайн", "ux design"],
    "Prototyping": ["прототипирование", "прототипы", "wireframes", "вайрфреймы"],
    "Design Systems": ["дизайн-система", "дизайн-системы", "design system"],
    "Adobe Photoshop": ["photoshop", "фотошоп"],
    "Adobe Illustrator": ["illustrator"],
    "Sketch": [],
    "Tilda": ["тильда"],
    "Usability Testing": ["юзабилити-тестирование", "usability testing", "юзабилити"],
    "Adaptive Design": ["адаптивная верстка", "адаптивный дизайн", "responsive design"],
    # Process / soft
    "Agile": ["scrum", "kanban"],
    "Jira": ["confluence"],
    "English": ["английский язык", "английский", "english b1", "english b2", "upper-intermediate", "intermediate"],
    "Testing": ["unit testing", "pytest", "unittest", "тестирование", "jest"],
    "OOP": ["ооп", "объектно-ориентированное программирование"],
    "Algorithms": ["алгоритмы", "структуры данных", "data structures"],
}


@lru_cache
def _alias_index() -> list[tuple[re.Pattern[str], str]]:
    entries: list[tuple[str, str]] = []
    for canonical, aliases in SKILLS.items():
        for alias in {canonical.lower(), *aliases}:
            entries.append((alias, canonical))
    # Longest aliases first so "spring boot" wins over "spring".
    entries.sort(key=lambda e: -len(e[0]))
    index = []
    for alias, canonical in entries:
        # Very short aliases (c, go, ml, ui...) only match as standalone tokens with exact case-insensitive
        # boundaries; letters, digits, '+', '#', '.' are word characters for this purpose.
        pattern = re.compile(rf"(?<![\w+#.\-]){re.escape(alias)}(?![\w+#\-]|\.\w)", re.IGNORECASE)
        index.append((pattern, canonical))
    return index


# Short aliases that are ordinary words in lowercase: they count only when written in this exact case.
_CASE_SENSITIVE = {
    "c": "C",
    "go": "Go",
    "ad": "AD",
    "ui": "UI",
    "ux": "UX",
    "ml": "ML",
    "dl": "DL",
    "tf": "TF",
    "ts": "TS",
    "иб": "ИБ",
    "rest": "REST",
    "make": "Make",
    "ооп": "ООП",
}


def canonical_skill(name: str) -> str:
    key = name.strip().lower()
    for canonical, aliases in SKILLS.items():
        if key == canonical.lower() or key in aliases:
            return canonical
    return name.strip()


def extract_skills(text: str) -> list[str]:
    """Find known skills mentioned in free text."""
    found: list[str] = []
    if not text:
        return found
    for pattern, canonical in _alias_index():
        for match in pattern.finditer(text):
            raw = match.group(0)
            required = _CASE_SENSITIVE.get(raw.lower())
            if required is not None and raw not in {required, required.upper()}:
                continue
            if canonical not in found:
                found.append(canonical)
            break
    return found


def normalize_skill_list(skills: list[str]) -> list[str]:
    result: list[str] = []
    for s in skills:
        if not s or not s.strip():
            continue
        c = canonical_skill(s)
        if c.lower() not in {r.lower() for r in result}:
            result.append(c)
    return result


def skill_key(name: str) -> str:
    return canonical_skill(name).lower()
