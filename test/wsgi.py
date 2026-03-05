import re

patterns = [
    (r'^$', "空字符串"),
    (r'hello/?$', "以hello或hello/结尾"),
    (r'world/?$', "以world或world/结尾"),
    (r'good/boy?$', "以good/bo或good/boy结尾"),
]

test_cases = [
    "",
    "hello",
    "hello/",
    "hello//",
    "world",
    "world/",
    "good/bo",
    "good/boy",
    "a good/bo",
    "a good/boy",
    "hello world",
    "good/boyy",
]

for pattern , desc in patterns:
    print(f"Mode: {pattern:15} Means: {desc}")
    compiled = re.compile(pattern)
    for test in test_cases:
        if compiled.match(test):
            print(f"Match: {test}")
    print()
