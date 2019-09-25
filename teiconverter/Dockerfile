FROM python:3.5.7-buster

ENV PROJECT_HOME=/srv/teiconverter

ENV VENV=${PROJECT_HOME}/venv
RUN python3 -m venv ${VENV}
ENV PYTHONUSERBASE=${VENV} PATH=${VENV}/bin:$PATH

WORKDIR ${PROJECT_HOME}

COPY requirements.txt ${PROJECT_HOME}/
RUN pip install -r requirements.txt


COPY server ${PROJECT_HOME}/server
COPY Stylesheets ${PROJECT_HOME}/xslt
COPY *.cfg *.conf *.sh *.in *.txt *.py ${PROJECT_HOME}/