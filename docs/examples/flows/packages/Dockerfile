FROM python:3.11-slim
WORKDIR /app
# kaos-lib, as in every step: keep these two lines.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel]==0.5.0"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
# Your own packages: pin them, so that two builds give the same image.
RUN pip install --no-cache-dir "pandas==2.2.3" "scikit-learn==1.5.2"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
