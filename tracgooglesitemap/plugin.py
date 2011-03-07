# -*- coding: utf-8 -*-
"""
 Copyright (c) 2010 by Martin Scharrer <martin@scharrer-online.de>
"""

__url__      = ur"$URL: http://trac-hacks.org/svn/googlesitemapplugin/0.11/tracgooglesitemap/plugin.py $"[6:-2]
__author__   = ur"$Author: martin_s $"[9:-2]
__revision__ = ur"$Rev: 9514 $"[6:-2]
__date__     = ur"$Date: 2010-11-24 21:42:18 +0100 (Wed, 24 Nov 2010) $"[7:-2]


from  trac.core       import  *
from  genshi.builder  import  tag
from  trac.web.api    import  IRequestHandler, RequestDone
from  trac.util.text  import  to_unicode
from  trac.config     import  Option, ListOption, BoolOption, IntOption, FloatOption
from  trac.resource   import  Resource
from  trac.ticket     import  Ticket
from  trac.util       import  format_datetime
from  trac.wiki       import  WikiPage

class GoogleSitemapPlugin(Component):
    """ Generates a Google compatible sitemap with all wiki pages and/or tickets.

     The sitemap can be compressed with the `compress_sitemap` option. In this case the XML file can be sent compressed in two different ways:
       * If the XML file (.xml) is requested it will be send with a gzip `content-encoding` if the requesting HTTP client supports it,
         i.e. sent a `accept-encoding` header with either includes '`gzip`' or indentical to '`*`'.
       * If a gzipped XML file is requested (.xml.gz) directly the compressed sitemap will be sent as gzip file (mime-type `application/x-gzip`).
         This is also done if the `sitemappath` ends in '`.gz`'.
    """
    implements ( IRequestHandler )

    rev = __revision__
    date = __date__

    sitemappath = Option('googlesitemap', 'sitemappath', 'sitemap.xml', 'Path of sitemap relative to Trac main URL (default: "sitemap.xml"). '
                                                                        'If this path ends in `.gz` the sidemap will automatically be compressed.')
    ignoreusers = ListOption('googlesitemap', 'ignore_users', 'trac', doc='Do not list wiki pages from this users (default: "trac")')
    ignorewikis = ListOption('googlesitemap', 'ignore_wikis', '', doc='List of wiki pages to not be included in sitemap')
    listrealms  = ListOption('googlesitemap', 'list_realms', 'wiki,ticket,report,roadmap,attachment,browser,timeline,homepage,contactform,fullblog', doc='Which realms should be listed. Supported are "wiki", "ticket", "report", "roadmap", "attachment", "browser", "timeline", "homepage", "contactform" and "fullblog".')
    compress_sitemap = BoolOption('googlesitemap', 'compress_sitemap', False, doc='Send sitemap compressed. Useful for larger sitemaps.')
    compression_level = IntOption('googlesitemap', 'compression_level', 6, doc='Compression level. Value range: 1 (low) to 9 (high). Default: 6')
    changefreq = Option('googlesitemap', 'change_frequency', '', 'Change frequency of URLs. Valid values: always, hourly, daily, weekly, monthly, yearly, never. Disabled if empty.')

    wiki_priority = ListOption('googlesitemap', 'wiki_priority', '', doc="""Wiki pages with increased priority.""")
    wiki_auto_priority = BoolOption('googlesitemap', 'wiki_auto_priority', False, doc="""Should top hierarchical wiki entries have increased priority automatically?""")
    wiki_auto_priority_ignore = ListOption('googlesitemap', 'wiki_auto_priority_ignore', '', doc="""Which top hierarchical wiki entries should be ignored for increased priority.""")

    default_priority = FloatOption('googlesitemap', 'default_priority', 0.8, doc="""Default entry priority.""")
    increased_priority = FloatOption('googlesitemap', 'increased_priority', 0.9, doc="""Increased entry priority.""")

    _urlset_attrs = {
              'xmlns':"http://www.sitemaps.org/schemas/sitemap/0.9",
              'xmlns:xsi':"http://www.w3.org/2001/XMLSchema-instance",
              'xsi:schemaLocation':"http://www.sitemaps.org/schemas/sitemap/0.9 http://www.sitemaps.org/schemas/sitemap/0.9/sitemap.xsd" 
            }

    def _get_sql_exclude(self, list):
      import re
      if not list:
        return ''
      star  = re.compile(r'(?<!\\)\*')
      ques  = re.compile(r'(?<!\\)\?')
      sql_excludelist = []
      sql_excludepattern = ''
      for pattern in list:
        pattern = pattern.replace('%',r'\%').replace('_',r'\_')
        npattern = star.sub('%', pattern)
        npattern = ques.sub('_', npattern)
        if pattern == npattern:
          sql_excludelist.append(pattern)
        else:
          sql_excludepattern = sql_excludepattern + " AND name NOT LIKE '%s' " % npattern
      sql_excludename = " AND name NOT in ('%s') " % "','".join(sql_excludelist)
      return sql_excludename + sql_excludepattern


    # IRequestHandler methods
    def match_request(self, req):
        path = '/' + self.sitemappath
        return req.path_info == path or (self.compress_sitemap and req.path_info == path + '.gz')

    def _fixtime(self, timestring):
        """Ensure that the timestring has a colon between hours and minute"""
        if not timestring.endswith('Z') and timestring[-3] != ':':
            return timestring[:-2] + ':' + timestring[-2:]
        else:
            return timestring

    def process_request(self, req):
        try:
            db = self.env.get_db_cnx()
            cursor = db.cursor()

            wiki_prioritylist = []
            wiki_prioritylist += self.wiki_priority

            if self.wiki_auto_priority:
                cursor.execute("SELECT DISTINCT name FROM wiki WHERE name LIKE '%/%' GROUP BY name ORDER BY name")
                wiki_prioritylist += [name for name in set([row[0].split('/', 1)[0] for row in cursor]) if name not in self.wiki_auto_priority_ignore]

            if 'wiki' in self.listrealms:
              sql_exclude = self._get_sql_exclude(self.ignorewikis)

              sql = "SELECT name,time,version FROM wiki AS w1 WHERE " \
                    "author NOT IN ('%s') "  % "','".join( self.ignoreusers ) + sql_exclude + \
                    "AND version=(SELECT MAX(version) FROM wiki AS w2 WHERE w1.name=w2.name) ORDER BY name "
              #self.log.debug(sql)
              cursor.execute(sql)
              urls = [ tag.url(
                              tag.loc( self.env.abs_href.wiki(name) ),
                              tag.lastmod( self._fixtime(format_datetime (time,'iso8601')) ),
                              self.changefreq and tag.changefreq( self.changefreq ) or '',
                              tag.priority(self.increased_priority) if name in wiki_prioritylist else tag.priority(self.default_priority)
                        ) for [name,time,version] in cursor if 'WIKI_VIEW' in req.perm(WikiPage(self.env, name, version).resource) ]
            else:
              urls = []
            
            if 'ticket' in self.listrealms and self.env.is_component_enabled('trac.ticket.'):
              cursor.execute(
                  "SELECT id,changetime FROM ticket"
              )
              urls.append( [ tag.url(
                              tag.loc( self.env.abs_href.ticket(ticketid) ),
                              tag.lastmod( self._fixtime(format_datetime (changetime,'iso8601')) ),
                              tag.priority(self.default_priority)
                        ) for [ticketid,changetime] in cursor if 'TICKET_VIEW' in req.perm(Ticket(self.env, ticketid).resource) ] )

            if 'report' in self.listrealms and self.env.is_component_enabled('trac.ticket.report'):
                if 'REPORT_VIEW' in req.perm:
                    urls.append( [ tag.url(
                                    tag.loc( self.env.abs_href('report') ),
                                    tag.priority(self.increased_priority)
                                   ) ] )
                cursor.execute('SELECT id FROM report ORDER BY id')
                urls.append( [ tag.url(
                                tag.loc( self.env.abs_href('report', report) ),
                                tag.priority(self.default_priority)
                          ) for [report] in cursor if 'REPORT_VIEW' in req.perm(Resource('report', report)) ] )

            if 'roadmap' in self.listrealms and self.env.is_component_enabled('trac.ticket.roadmap'):
                if 'ROADMAP_VIEW' in req.perm or 'MILESTONE_LIST' in req.perm:
                    urls.append( [ tag.url(
                                    tag.loc( self.env.abs_href('roadmap') ),
                                    tag.priority(self.increased_priority)
                                   ) ] )
                cursor.execute('SELECT name FROM milestone ORDER BY name')
                urls.append( [ tag.url(
                                tag.loc( self.env.abs_href('milestone', milestone) ),
                                tag.priority(self.default_priority)
                          ) for [milestone] in cursor if 'MILESTONE_VIEW' in req.perm(Resource('milestone', milestone)) ] )

            if 'attachment' in self.listrealms:
                cursor.execute('SELECT type,id,filename,time FROM attachment')
                urls.append( [ tag.url(
                                tag.loc( self.env.abs_href('attachment', type, id, filename) ),
                                tag.lastmod( self._fixtime(format_datetime (time,'iso8601')) ),
                                tag.priority(self.default_priority)
                          ) for [type,id,filename,time] in cursor if 'ATTACHMENT_VIEW' in req.perm(Attachment(self.env, type, id, filename)) ] )
            
            if 'browser' in self.listrealms and self.env.is_component_enabled('trac.versioncontrol.') and 'BROWSER_VIEW' in req.perm:
                urls.append( [ tag.url(
                                tag.loc( self.env.abs_href('browser') ),
                                tag.priority(self.increased_priority)
                               ) ] )
            
            if 'timeline' in self.listrealms and self.env.is_component_enabled('trac.timeline') and 'TIMELINE_VIEW' in req.perm:
                urls.append( [ tag.url(
                                tag.loc( self.env.abs_href('timeline') ),
                                tag.priority(self.increased_priority)
                               ) ] )

            if 'homepage' in self.listrealms:
                 urls.append( [ tag.url(
                                 tag.loc( self.env.abs_href() ),
                                 tag.priority(1.0)
                                ) ] )
            
            # TODO: Define extension point for those and move them to separate plugins

            # Support for ContactFormPlugin
            if 'contactform' in self.listrealms and self.env.is_component_enabled('contactform.'):
                urls.append( [ tag.url(
                                tag.loc( self.env.abs_href('contact') ),
                                tag.priority(self.increased_priority)
                               ) ] )

            # Support for FullBlogPlugin
            if 'fullblog' in self.listrealms and self.env.is_component_enabled('tracfullblog.'):
                cursor.execute("SELECT DISTINCT name,MAX(version_time) FROM fullblog_posts GROUP BY name ORDER BY name")
                urls.append( [ tag.url(
                              tag.loc( self.env.abs_href('blog', name) ),
                              tag.lastmod( self._fixtime(format_datetime (changetime,'iso8601')) ),
                              tag.priority(self.default_priority)
                          ) for [name,changetime] in cursor if 'BLOG_VIEW' in Resource('blog', name) ] )
            
            xml = tag.urlset(urls, **self._urlset_attrs)
            content = xml.generate().render('xml','utf-8')

            accept_enc  = req.get_header('accept-encoding')
            accept_gzip = accept_enc and ( accept_enc.find('gzip') != -1 or accept_enc == '*' )
            compressed  = self.sitemappath.endswith('.gz') or req.path_info == '/' + self.sitemappath + '.gz'
            if compressed or (self.compress_sitemap and accept_gzip):
              import StringIO
              from gzip import GzipFile
              gzbuf = StringIO.StringIO()
              gzfile = GzipFile(mode='wb', fileobj=gzbuf, compresslevel=self.compression_level)
              gzfile.write(content)
              gzfile.close()
              zcontent = gzbuf.getvalue()
              gzbuf.close()

              req.send_response(200)
              req.send_header('Cache-control', 'must-revalidate')
              if compressed:
                req.send_header('Content-Type', 'application/x-gzip')
              else:
                req.send_header('Content-Type', 'text/xml;charset=utf-8')
                req.send_header('Content-Encoding', 'gzip')
              req.send_header('Content-Length', len(zcontent))
              req.end_headers()

              if req.method != 'HEAD':
                  req.write(zcontent)
              raise RequestDone
            else:
              req.send( content, content_type='text/xml', status=200)

        except RequestDone:
            pass
        except Exception, e:
            self.log.error(e)
            req.send_response(500)
            req.end_headers()
        raise RequestDone



