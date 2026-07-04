import ssl
from django.core.mail.backends.smtp import EmailBackend as DjangoEmailBackend

class Python313EmailBackend(DjangoEmailBackend):
    """
    A wrapper that manages the SMTP network connection, patched to support Python 3.12+ / 3.13
    by avoiding deprecated/removed keyfile/certfile parameters in SMTP.starttls() and SMTP_SSL().
    """
    def open(self):
        if self.connection:
            return False

        from django.core.mail.utils import DNS_NAME
        connection_params = {'local_hostname': DNS_NAME.get_fqdn()}
        if self.timeout is not None:
            connection_params['timeout'] = self.timeout

        # Under Python 3.12+, smtplib.SMTP_SSL does not accept keyfile/certfile.
        # We must use context instead.
        if self.use_ssl:
            if self.ssl_keyfile or self.ssl_certfile:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                # pyrefly: ignore [bad-argument-type]
                context.load_cert_chain(certfile=self.ssl_certfile, keyfile=self.ssl_keyfile)
                connection_params['context'] = context

        try:
            # pyrefly: ignore [bad-argument-type]
            self.connection = self.connection_class(self.host, self.port, **connection_params)

            if not self.use_ssl and self.use_tls:
                if self.ssl_keyfile or self.ssl_certfile:
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    # pyrefly: ignore [bad-argument-type]
                    context.load_cert_chain(certfile=self.ssl_certfile, keyfile=self.ssl_keyfile)
                    self.connection.starttls(context=context)
                else:
                    self.connection.starttls()

            if self.username and self.password:
                self.connection.login(self.username, self.password)
            return True
        except OSError:
            if not self.fail_silently:
                raise
