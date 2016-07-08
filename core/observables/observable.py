from __future__ import unicode_literals

from datetime import datetime
import operator
import pytz

from mongoengine import *
from flask_mongoengine.wtf import model_form
from flask import url_for

from core.helpers import iterify
from core.database import Node, TagListField
from core.observables import ObservableTag, Tag
from core.entities import Entity
from core.errors import ObservableValidationError


class Observable(Node):
    """Base class for Observables in Yeti

    Observables describe elements that can be seen in investigations,
    incidents, reports, intelligence, etc. They are usually technical data about
    specific threats or actors.

    Attributes:
        value: The observable's technical value (the observed URL, hostname, IP address...)
        sources: An array of strings that define how the observable was inserted
        description: A free-text description of the observable
        context: A JSON object providing extra information as to why the observable was added. Context can be added trough the API or through Feeds
        tags: An array of :class:`core.observables.tag.ObservableTag` objects
        last_analyses: An array of JSON objects indicating the last analysis time for a particular analytics
        created: Creation date
        last_tagged: Date when a given observable was last tagged
        exclude_fields: Fields to be excluded from automatic form creation
    """

    DISPLAY_FIELDS = [("value", "Value"), ("context", "Context"), ("tags", "Tags")]

    value = StringField(verbose_name="Value", required=True, unique=True, sparse=True, max_length=1024)
    sources = ListField(StringField(), verbose_name="Sources")
    description = StringField(verbose_name="Description")
    context = ListField(DictField(), verbose_name="Context")
    tags = ListField(EmbeddedDocumentField(ObservableTag), verbose_name="Tags")
    last_analyses = DictField(verbose_name="Last analyses")

    created = DateTimeField(default=datetime.utcnow)
    last_tagged = DateTimeField(default=None)

    exclude_fields = ['sources', 'context', 'last_analyses', 'created', 'attached_files', 'last_tagged']

    meta = {
        "allow_inheritance": True,
        "indexes": [
            "tags",
            "last_analyses",
        ]
    }

    @classmethod
    def get_form(klass):
        """Gets the appropriate form for a given obseravble"""
        form = model_form(klass, exclude=klass.exclude_fields)
        form.tags = TagListField()
        return form

    def __unicode__(self):
        return u"{} ({} context)".format(self.value, len(self.context))

    @staticmethod
    def guess_type(string):
        """Tries to guess the type of observable given a ``string``.

        Args:
            string: The string that will be used to guess the observable type from.

        Returns:
            An observable Class.

        Raises:
            ObservableValidationError if no type could be guessed.
        """
        from core.observables import Url, Ip, Hostname, Email, Hash

        if string and string.strip() != '':
            for t in [Url, Ip, Email, Hostname, Hash]:
                if t.check_type(string):
                    return t
            else:
                raise ObservableValidationError("{} was not recognized as a viable datatype".format(string))

    @classmethod
    def add_text(cls, text):
        """Adds and returns an observable for a given string.

        Args:
            text: the text that will be used to add an Observable from.

        Returns:
            A saved Observable instance.

        """
        return Observable.guess_type(text).get_or_create(value=text)

    @staticmethod
    def check_type(txt):
        raise NotImplementedError("Implement this in subclasses")

    @staticmethod
    def change_all_tags(old_tags, new_tag):
        """Changes tags on all observables

        Args:
            old_tags: A string or array of strings representing tag names to change
            new_tag: The new tag name by which all ``old_tags`` should be replaced

        """
        old_tags = iterify(old_tags)
        for o in Observable.objects(tags__name__in=old_tags):
            for old_tag in old_tags:
                o.change_tag(old_tag, new_tag)

    def add_context(self, context, replace_source=None):
        """Adds context to an Observable.

        "Context" is represented by a JSON object (or Python ``dict()``) that will
        be added to the Observable's ``context`` set. Context should provide information
        on why the Observable has been added to the database.

        Context can be any information, but it needs to have a ``source`` key that can
        point the analyst to the source of the context.

        Args:
            context: a JSON object representing the context to be added.
            replace_source: If defined, contexts having a ``source`` attribute
                            set to ``replace_source`` will be deleted before insert

        Returns:
            A fresh instance of the Observable as it exists in the database.

        """
        assert 'source' in context
        context = {k: v for k, v in sorted(context.items(), key=operator.itemgetter(0))}
        if replace_source:
            # This does not work : cannot traverse and set context atomically
            # self.modify({"context__source": c}, set__context__S=context)
            self.modify(pull__context__source=replace_source)
        self.modify(add_to_set__context=context)

        return self.reload()

    def remove_context(self, context):
        """Removes Context from an observable.

        Args:
            context: a JSON object representing the context to be removed.

        Returns:
            A fresh instance of the Observable as it exists in the database.

        """
        context = {k: v for k, v in sorted(context.items(), key=operator.itemgetter(0))}
        self.modify(pull__context=context)
        return self.reload()

    def add_source(self, source):
        """Adds a source to the observable instance

        Args:
            source: a string to add to the array of sources.
        """
        return self.modify(add_to_set__sources=source)

    def get_tags(self, fresh=True):
        """Returns an array of strings containing an observables' fresh tags names.

        Args:
            fresh: set to ``False`` to also include non-fresh tags in the result

        Returns:
            Array of strings containing an observables' fresh tags names.

        """
        return [t.name for t in self.tags if (t.fresh or not fresh)]

    def find_tags(self):
        # find related tags and count them
        new_tags = {}
        for tag in self.tags:
            tag = Tag.objects.get(name=tag.name)
            for produces in tag.produces:
                new_tags[produces] = new_tags.get(tag, 0) + 1

        # remove already known tags
        localtags = [tag.name for tag in self.tags]
        for tag in new_tags.copy():
            if tag in localtags:
                new_tags.pop(tag)

        return new_tags

    def has_tag(self, tag_to_search):
        for tag in self.tags:
            if tag.name == tag_to_search:
                return True
        else:
            return False

    def change_tag(self, old_tag, new_tag):
        if not self.modify({"tags__name": old_tag, "tags__name__ne": new_tag}, set__tags__S__name=new_tag):
            self.modify({"tags__name": old_tag}, pull__tags__name=old_tag)
            self.modify({"tags__name": new_tag}, set__tags__S__last_seen=datetime.utcnow())
        return self.reload()

    def untag(self, tags):
        for tag in iterify(tags):
            self.modify(pull__tags__name=tag)

    def tag(self, new_tags, strict=False, expiration=None):
        """Tags an observable.

        An observable can be tagged to add more information as to what it represents.

        Args:
            new_tags:
                An array of strings to tag the observable with.
            strict:
                Set to ``True`` to replace all existing tags with the ``new_tags``.
            expiration:
                Timedelta field after which the Tag will not be considered fresh anymore.

        Returns:
            A fresh Observable instance as reloaded from the database.

        """

        new_tags = iterify(new_tags)

        if strict:
            remove = set([t.name for t in self.tags]) - set(new_tags)
            for tag in remove:
                self.modify(pull__tags__name=tag)

        tagged = False
        for new_tag in new_tags:
            if new_tag.strip() != '':
                tagged = True

                new_tag = Tag(name=new_tag)
                new_tag.clean()

                try:  # check if tag is a replacement
                    tag = Tag.objects.get(replaces=new_tag.name)
                except DoesNotExist:
                    tag = Tag.get_or_create(name=new_tag.name)

                if not expiration:
                    expiration = tag.default_expiration

                extra_tags = tag.produces + [tag]

                # search for related entities and link them
                for e in Entity.objects(tags__in=[tag.name]):
                    self.active_link_to(e, 'Tagged', 'tags', clean_old=True)

                for tag in extra_tags:
                    if not self.modify({"tags__name": tag.name}, set__tags__S__fresh=True, set__tags__S__last_seen=datetime.utcnow()):
                        self.modify(push__tags=ObservableTag(name=tag.name, expiration=expiration))
                        tag.modify(inc__count=1)

        if tagged:
            self.update(set__last_tagged=datetime.utcnow())

        return self.reload()

    def get_last_tagged(self):
        if not self.last_tagged:
            last = datetime(1970, 1, 1)
            for tag in self.tags:
                if tag.last_seen > last:
                    last = tag.last_seen
            self.update(set__last_tagged=last)
            return last
        else:
            return self.last_tagged


    def expire_tags(self):
        for tag in self.tags:
            if tag.expiration and (tag.last_seen + tag.expiration) < datetime.utcnow().replace(tzinfo=pytz.UTC):
                tag.fresh = False
        return self.save()

    def fresh_tags(self):
        return [tag for tag in self.tags if tag.fresh]

    def analysis_done(self, module_name):
        ts = datetime.utcnow()
        return self.modify(**{"set__last_analyses__{}".format(module_name): ts})

    def info(self):
        i = {k: v for k, v in self._data.items() if k in ["value", "context", "last_analyses", "created", "sources"]}
        i['tags'] = [t.info() for t in self.tags]
        if self.id:
            i['id'] = str(self.id)
        i['type'] = self.__class__.__name__
        i['url'] = url_for("api.Observable:post", id=str(self.id), _external=True)
        i['human_url'] = url_for("frontend.ObservableView:get", id=str(self.id), _external=True)
        return i
