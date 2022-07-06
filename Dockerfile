FROM python:slim

RUN useradd titulo

WORKDIR /home/titulo

COPY requirements.txt requirements.txt
RUN python -m venv venv
RUN venv/bin/pip install -r requirements.txt
RUN venv/bin/pip install gunicorn pymysql cryptography

COPY app app
COPY migrations migrations
COPY titulo.py config.py boot.sh ./
RUN chmod a+x boot.sh

ENV FLASK_APP titulo.py

RUN chown -R titulo:titulo ./
USER titulo

EXPOSE 5000
ENTRYPOINT ["./boot.sh"]
