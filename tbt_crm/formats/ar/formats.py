# تنسيقات عربية مناسبة للعمل في إسرائيل: أرقام غربية، نقطة عشرية، تاريخ يوم/شهر/سنة، ساعة 24.
DATE_FORMAT = "d/m/Y"
TIME_FORMAT = "H:i"
DATETIME_FORMAT = "d/m/Y H:i"
YEAR_MONTH_FORMAT = "m/Y"
MONTH_DAY_FORMAT = "d/m"
SHORT_DATE_FORMAT = "d/m/Y"
SHORT_DATETIME_FORMAT = "d/m/Y H:i"
FIRST_DAY_OF_WEEK = 0  # الأحد

DATE_INPUT_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y"]
TIME_INPUT_FORMATS = ["%H:%M", "%H:%M:%S"]
DATETIME_INPUT_FORMATS = [
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M",
]

DECIMAL_SEPARATOR = "."
THOUSAND_SEPARATOR = ","
NUMBER_GROUPING = 3
