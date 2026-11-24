from aiogram.fsm.state import State, StatesGroup


class NewAd(StatesGroup):
    content = State()


class Compose(StatesGroup):
    picking_ad = State()
    choosing_channels = State()
    choosing_time = State()
    choosing_repeat = State()
