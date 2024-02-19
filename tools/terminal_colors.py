


class TermColor:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

    def getColorfulText(text: str) -> str:
        mappingOfColors = [
            TermColor.BLUE,
            TermColor.GREEN,
            TermColor.WARNING,
            TermColor.CYAN,
            TermColor.FAIL
        ]
        newstr = ""
        count = 0
        for char in text:
            newstr += mappingOfColors[count]
            newstr += char
            count += 1
            if count >= len(mappingOfColors):
                count = 0
        newstr += TermColor.ENDC

        return newstr
    
    def makeBlue(text: str) -> str:
        return TermColor.BLUE + text + TermColor.ENDC
    def makeCyan(text: str) -> str:
        return TermColor.CYAN + text + TermColor.ENDC
    def makeGreen(text: str) -> str:
        return TermColor.GREEN + text + TermColor.ENDC
    def makeWarning(text: str) -> str:
        return TermColor.WARNING + text + TermColor.ENDC
    def makeFail(text: str) -> str:
        return TermColor.FAIL + text + TermColor.ENDC