from sqlmesh.core.linter.rule import Rule

class CustomDummyRule(Rule):
    def check_model(self, model):
        return None
