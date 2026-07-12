/*
 * Alf recon - compact Android SSL unpinning for Frida.
 *
 * Covers the common pinning vectors (default TrustManager, OkHttp3
 * CertificatePinner, Conscrypt TrustManagerImpl). If the Alf app still won't
 * decrypt, replace this file with the maintained community script:
 *   https://github.com/httptoolkit/frida-interception-and-unpinning
 *
 * Usage: frida -U -f se.lf.alf -l frida/ssl-unpinning.js
 */
setTimeout(function () {
  Java.perform(function () {
    // 1) Replace the app's TrustManager with a permissive one.
    try {
      const X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
      const SSLContext = Java.use('javax.net.ssl.SSLContext');
      const TrustAll = Java.registerClass({
        name: 'com.recon.TrustAllManager',
        implements: [X509TrustManager],
        methods: {
          checkClientTrusted: function () {},
          checkServerTrusted: function () {},
          getAcceptedIssuers: function () { return []; },
        },
      });
      const init = SSLContext.init.overload(
        '[Ljavax.net.ssl.KeyManager;',
        '[Ljavax.net.ssl.TrustManager;',
        'java.security.SecureRandom');
      init.implementation = function (km, tm, sr) {
        init.call(this, km, [TrustAll.$new()], sr);
      };
      console.log('[+] SSLContext.init hooked');
    } catch (e) { console.log('[-] SSLContext hook failed: ' + e); }

    // 2) OkHttp3 certificate pinner.
    try {
      const CertificatePinner = Java.use('okhttp3.CertificatePinner');
      CertificatePinner.check.overload('java.lang.String', 'java.util.List')
        .implementation = function (host) {
          console.log('[+] OkHttp CertificatePinner.check bypassed for ' + host);
        };
    } catch (e) { console.log('[-] OkHttp not present: ' + e); }

    // 3) Conscrypt TrustManagerImpl (Android 7+).
    try {
      const TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
      TrustManagerImpl.verifyChain
        .implementation = function (chain, authType, host, clientAuth, ocspData, tlsSctData) {
          console.log('[+] TrustManagerImpl.verifyChain bypassed for ' + host);
          return chain;
        };
    } catch (e) { console.log('[-] TrustManagerImpl.verifyChain hook failed: ' + e); }

    // 4) Conscrypt TrustManagerImpl.checkTrustedRecursive - the real cert-validation
    //    entrypoint on modern Android. A non-throwing return = the chain is accepted.
    try {
      const TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
      const ArrayList = Java.use('java.util.ArrayList');
      TrustManagerImpl.checkTrustedRecursive.overloads.forEach(function (ovl) {
        ovl.implementation = function () {
          return ArrayList.$new();
        };
      });
      console.log('[+] TrustManagerImpl.checkTrustedRecursive hooked (' +
        TrustManagerImpl.checkTrustedRecursive.overloads.length + ' overloads)');
    } catch (e) { console.log('[-] checkTrustedRecursive hook failed: ' + e); }
  });
}, 0);
