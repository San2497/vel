from models import Stand

STANDS: list[Stand] = [
    Stand(id="S101", title="Meteostanice s Raspberry Pi", authors=["Jana Nováková", "Petr Svoboda"], class_name="C3b", floor=1, room="101"),
    Stand(id="S102", title="Hra Hledání pokladu v Unity", authors=["Tomáš Dvořák"], class_name="C2a", floor=1, room="102"),
    Stand(id="S103", title="Chytrý květináč s automatickou zálivkou", authors=["Eliška Černá", "Adam Veselý"], class_name="C3a", floor=1, room="103"),
    Stand(id="S201", title="Rezervační systém pro školní učebny", authors=["Marek Horák"], class_name="C4a", floor=2, room="201"),
    Stand(id="S202", title="Mobilní aplikace pro jídelníček", authors=["Klára Marková", "Ondřej Pokorný"], class_name="C4b", floor=2, room="202"),
    Stand(id="S203", title="Rozpoznávání rostlin pomocí AI", authors=["Lukáš Král"], class_name="C4a", floor=2, room="203"),
    Stand(id="S301", title="Robotické rameno řízené Arduinem", authors=["Filip Beneš", "Matěj Růžička"], class_name="C3b", floor=3, room="301"),
    Stand(id="S302", title="Webový portál školního časopisu", authors=["Tereza Fialová"], class_name="C2b", floor=3, room="302"),
    Stand(id="S303", title="Simulace dopravy na křižovatce", authors=["David Šimek", "Natálie Kučerová"], class_name="C4b", floor=3, room="303"),
]

STANDS_BY_ID: dict[str, Stand] = {s.id: s for s in STANDS}
