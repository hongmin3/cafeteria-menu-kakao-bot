"""휴일 이름, 전일 휴무, 끼니별 휴무를 음식·행사 문구와 구분한다."""
from dataclasses import dataclass
import re


MEALS = {'조식': '조식', '아침': '조식', '중식': '중식', '점심': '중식', '석식': '석식', '저녁': '석식'}
HOLIDAY = (
    r'(?:신정|새해첫날|설날|설(?:연휴|명절)|삼일절|3[.·ㆍ]?1절|어린이날|부처님오신날|'
    r'석가탄신일|현충일|광복절|개천절|한글날|추석|한가위|성탄절|크리스마스|'
    r'근로자의날|노동절|(?:대체|임시)?공휴일|대체휴일|휴일|명절|연휴)(?:연휴|명절)?'
)
CLOSURE = r'(?:(?:휴무|휴점|휴업|미운영|미제공)(?:입니다|합니다|예정)?|운영없음|제공없음|운영하지않음|운영하지않습니다)(?:안내)?'
REASON = r'(?:로(?:인해|인한)?|기간(?:동안)?|동안)?'
NO_SERVICE_PATTERNS = re.compile(r'휴무|휴점|휴업|미운영|미제공|운영\s*없|제공\s*없|운영\s*하지\s*않')
OPEN_PATTERNS = re.compile(r'정상\s*(?:운영|제공)|휴무\s*없|미운영\s*아님')
INFERRED_SUFFIX = ' (식당 미운영)'


def compact_notice(text: str) -> str:
    text = re.sub(r'\([월화수목금토일]\)', '', text)
    return re.sub(r'[^가-힣A-Za-z0-9.·ㆍ]', '', text)


@dataclass(frozen=True)
class ServiceNotice:
    meals: tuple[str, ...] = ()
    inferred: bool = False


def classify_notice(text: str) -> ServiceNotice | None:
    """전체 문구가 안내일 때만 분류한다. 음식명이 섞이면 판정하지 않는다."""
    if OPEN_PATTERNS.search(text):
        return None
    compact = compact_notice(text)
    named = tuple(dict.fromkeys(MEALS[m.group()] for m in re.finditer('|'.join(MEALS), compact)))
    remainder = re.sub(r'[·ㆍ]', '', re.sub('|'.join(MEALS), '', compact))
    # 끼니 이름은 전일 휴무보다 먼저 본다. `석식 공휴일 미운영`도 석식만 쉰다.
    if named and re.fullmatch(rf'(?:{HOLIDAY}{REASON})?(?:식당)?{CLOSURE}', remainder):
        return ServiceNotice(meals=named)
    if re.fullmatch(rf'(?:{HOLIDAY}{REASON})?(?:식당|전사|회사|대체){CLOSURE}', compact):
        return ServiceNotice()
    if re.fullmatch(rf'{HOLIDAY}{REASON}{CLOSURE}', compact):
        return ServiceNotice()
    if re.fullmatch(HOLIDAY, compact):
        return ServiceNotice(inferred=True)
    return None


def is_inferred_notice(entry) -> bool:
    if entry.category != '안내' or entry.status != 'no_service':
        return False
    # 파서가 이름만으로 만든 안내만 제거할 수 있다. 명시된 휴무는 보존한다.
    messages = entry.menu_text.split(' · ')
    return all(message.endswith(INFERRED_SUFFIX) and
               (notice := classify_notice(message[:-len(INFERRED_SUFFIX)])) is not None and
               notice.inferred for message in messages)
