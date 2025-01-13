import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from playwright.async_api import async_playwright
import requests
from bs4 import BeautifulSoup
import time

from credentials import EMAIL, APP_PASSWORD, RECIPIENT, USER_FULL_NAME, USER_TIE


async def get_session(playwright):
    gbody = None
    cookies = None
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()

    # Intercept requests to capture cookies and body
    async def intercept_request(route, request):
        nonlocal gbody, cookies
        if "icp.administracionelectronica.gob.es/icpplustieb/acCitar" in request.url:
            gbody = request.post_data
            cookies = await context.cookies()
        await route.continue_()

    await page.route("**/*", intercept_request)

    await page.goto(
        "https://icp.administracionelectronica.gob.es/icpplustieb/citar?p=12&locale=es",
        wait_until="networkidle",
        timeout=120000  # Set timeout to 120 seconds
    )
    await page.select_option(".mf-input__xl", "99")  # Select 'oficina' (Barcelona)
    await page.evaluate("cargaMensajesTramite()")
    await asyncio.sleep(1)

    await page.select_option(".mf-input__l", "4010")  # Select 'tramite'
    await page.evaluate("eliminarSeleccionOtrosGrupos(0); cargaMensajesTramite()")
    await asyncio.sleep(1)

    await page.evaluate("envia()")
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(1)

    await page.fill("#txtIdCitado", USER_TIE)
    await page.fill("#txtDesCitado", USER_FULL_NAME)
    await page.evaluate("envia()")
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(1)

    await browser.close()
    return gbody, cookies


def send_email(subject, body):
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL
        msg["To"] = RECIPIENT
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL, APP_PASSWORD)
            server.sendmail(EMAIL, RECIPIENT, msg.as_string())
        print("Email sent successfully.")
    except Exception as e:
        print("Failed to send email:", str(e))


async def main():
    async with async_playwright() as playwright:
        gbody, cookies = await get_session(playwright)

        while True:
            try:
                cookies_str = "; ".join(
                    [f"{cookie['name']}={cookie['value']}" for cookie in cookies]
                )
                headers = {
                    "Accept": "text/html; charset=utf-8",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Cookie": cookies_str,
                }
                response = requests.post(
                    "https://icp.administracionelectronica.gob.es/icpplustieb/acCitar",
                    headers=headers,
                    data=gbody,
                )
                if response.status_code != 200:
                    print("Session expired or error occurred. Refreshing session.")
                    gbody, cookies = await get_session(playwright)
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                options = soup.select(".mf-input__xl option")
                citas = [
                    {"oficina": opt["value"], "oficina_name": opt.text}
                    for opt in options
                    if "Seleccionar" not in opt.text
                ]

                if citas:
                    subject = "Available Appointments Found"
                    body = "\n".join(
                        [f"{index + 1} - {cita['oficina_name']}" for index, cita in enumerate(citas)]
                    )
                    print(subject)
                    print(body)
                    send_email(subject, body)

                time.sleep(35)
            except Exception as e:
                print("Error:", str(e))
                time.sleep(35)


if __name__ == "__main__":
    asyncio.run(main())
