"""Selenium tests for login page."""
from .pages import login



def test_login_and_logout(selenium, teacher):
    login_pg = login.LoginPage(selenium)

    login_pg.go_to_login_page()

    assert not login_pg.is_user_logged_in

    home_pg = login_pg.login(
        email=teacher.user.email,
        password=teacher.raw_password
        )

    assert home_pg.is_user_logged_in
    assert home_pg.username_text == teacher.user.email

    home_pg.click_logout()

    assert not home_pg.is_user_logged_in
