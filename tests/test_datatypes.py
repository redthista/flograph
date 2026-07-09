import pandas as pd
import pytest

from flopy.core import PortType, can_connect, validate_value


class TestCanConnect:
    def test_same_type(self):
        for t in PortType:
            assert can_connect(t, t)

    def test_any_connects_both_ways(self):
        for t in PortType:
            assert can_connect(PortType.ANY, t)
            assert can_connect(t, PortType.ANY)

    def test_widening_to_object(self):
        for t in (PortType.DATAFRAME, PortType.SERIES, PortType.NUMBER,
                  PortType.STRING, PortType.BOOL, PortType.FIGURE):
            assert can_connect(t, PortType.OBJECT)

    def test_object_does_not_narrow(self):
        assert not can_connect(PortType.OBJECT, PortType.DATAFRAME)
        assert not can_connect(PortType.OBJECT, PortType.NUMBER)

    def test_incompatible_concrete_types(self):
        assert not can_connect(PortType.NUMBER, PortType.STRING)
        assert not can_connect(PortType.SERIES, PortType.DATAFRAME)
        assert not can_connect(PortType.DATAFRAME, PortType.SERIES)


class TestValidateValue:
    def test_any_and_object_accept_everything(self):
        for value in (None, 1, "x", object(), pd.DataFrame()):
            assert validate_value(value, PortType.ANY) is None
            assert validate_value(value, PortType.OBJECT) is None

    def test_number(self):
        assert validate_value(1, PortType.NUMBER) is None
        assert validate_value(1.5, PortType.NUMBER) is None
        assert validate_value(True, PortType.NUMBER) is not None  # bool != number
        assert validate_value("1", PortType.NUMBER) is not None

    def test_bool_and_string(self):
        assert validate_value(True, PortType.BOOL) is None
        assert validate_value(1, PortType.BOOL) is not None
        assert validate_value("hi", PortType.STRING) is None
        assert validate_value(3, PortType.STRING) is not None

    def test_pandas_types(self):
        df = pd.DataFrame({"a": [1]})
        assert validate_value(df, PortType.DATAFRAME) is None
        assert validate_value(df["a"], PortType.SERIES) is None
        assert validate_value(df["a"], PortType.DATAFRAME) is not None
        assert validate_value(df, PortType.SERIES) is not None

    def test_none_rejected_for_concrete_types(self):
        message = validate_value(None, PortType.DATAFRAME)
        assert message is not None and "None" in message

    def test_figure(self):
        from matplotlib.figure import Figure
        assert validate_value(Figure(), PortType.FIGURE) is None
        assert validate_value("not a figure", PortType.FIGURE) is not None
